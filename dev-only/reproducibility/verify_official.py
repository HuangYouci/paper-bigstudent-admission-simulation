"""依官方 PDF 系組代碼逐系核對普通生門檻及倍率總和。"""
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

import pdfplumber

PAPER = Path(__file__).resolve().parents[2]


def parse_tables(pdf_path):
    """只讀取指定普通生欄位，拒絕重複代碼與表格位移。"""
    records = {}
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, 1):
            for table in page.extract_tables():
                for row in table:
                    if not row or not re.fullmatch(r'\d{4}', row[0] or ''):
                        continue
                    if len(row) != 12:
                        raise ValueError('官方表格欄位數改變')
                    code = row[0]
                    if code in records:
                        raise ValueError('官方代碼重複')
                    value = (row[5] or '').strip()
                    score = float(value) if re.fullmatch(r'\d+\.\d+', value) else None
                    multipliers = re.findall(r'x(\d+(?:\.\d+)?)', row[3] or '')
                    records[code] = {'code': code, 'page': page_number, 'ordinary_cutoff': score,
                                     'weight_total': sum(map(float, multipliers)),
                                     'count_including_extra': row[4], 'school': row[1], 'department': row[2]}
    return records, page_count


def main(repo):
    """以凍結資料庫串接系組代碼，不從名稱猜測。"""
    source = PAPER / 'sources/official/115_result_school_data.pdf'
    records, pages = parse_tables(source)
    manifest = json.loads((PAPER / 'data/manifest.json').read_text())
    raw = subprocess.check_output(['git', 'show', f"{manifest['verifiableResearchCommit']}:lib/database.db"], cwd=repo)
    if hashlib.sha256(raw).hexdigest() != manifest['sourceHashes']['lib/database.db']:
        raise ValueError('歷史資料庫雜湊不符')
    db = sqlite3.connect(':memory:')
    db.deserialize(raw)
    db.execute('PRAGMA query_only=ON')
    codes = dict(db.execute('SELECT dept_group_id, 學系代碼 FROM ast_data WHERE D_datayear=2026'))
    benchmark = list(csv.DictReader(io.StringIO((PAPER / 'data/department-benchmark.csv').read_text())))
    checked = []
    for row in benchmark:
        code = str(codes[int(row['gid'])]).zfill(4)
        official = records.get(code)
        if official is None or official['ordinary_cutoff'] is None:
            raise ValueError(f'官方普通生門檻缺失：{code}')
        if abs(official['ordinary_cutoff'] - float(row['actual'])) > 1e-9:
            raise ValueError(f'普通生門檻不符：{code}')
        if abs(official['weight_total'] - float(row['weightTotal'])) > 1e-9:
            raise ValueError(f'採計倍率總和不符：{code}')
        checked.append({'gid': row['gid'], 'code': code, 'page': official['page'],
                        'ordinary_cutoff': official['ordinary_cutoff'], 'weight_total': official['weight_total']})
    db.close()
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=list(checked[0]))
    writer.writeheader()
    writer.writerows(checked)
    (PAPER / 'data/official-truth-audit.csv').write_text(output.getvalue())
    summary = {'checkedAt': '2026-10-08', 'url': 'https://www.uac.edu.tw/115data/115_result_school_data.pdf',
               'pdfSHA256': hashlib.sha256(source.read_bytes()).hexdigest(), 'pages': pages,
               'officialDepartmentRows': len(records), 'evaluatedDepartments': len(checked),
               'ordinaryCutoffMismatches': 0, 'weightTotalMismatches': 0,
               'auditCSV_SHA256': hashlib.sha256(output.getvalue().encode()).hexdigest(),
               'note': '只將普通生錄取分數作為真值；含外加錄取人數不被當成普通生配置容量。'}
    (PAPER / 'data/official-truth-audit.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('請提供唯讀平台 repository 絕對路徑')
    main(sys.argv[1])
