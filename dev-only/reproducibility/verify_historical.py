"""核對歷史基準的 2025 年普通生門檻與逐科倍率，平台全程唯讀。"""
from pathlib import Path
import csv
import hashlib
import json
import sys
import math
import re
import sqlite3
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
import pdfplumber

PAPER = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from frozen_db import frozen_database_bytes  # noqa: E402
LABELS = {'國': '採計國文', '英': '採計英文', '數A': '採計數學A',
          '數B': '採計數學B', '社': '採計社會', '自': '採計自然',
          '數甲': '採計數學甲', '數乙': '採計數學乙', '物': '採計物理',
          '化': '採計化學', '生': '採計生物', '歷': '採計歷史',
          '地': '採計地理', '公': '採計公民'}


def positive(value):
    """將空白或零門檻視為缺值，拒絕非有限及負值。"""
    if value is None or str(value).strip() in ('', '0', '-----'):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError('門檻數值不合法')
    return number if number > 0 else None


def parse_weights(text):
    """逐科解析採計倍率；不以總和代替科目與倍率一致性。"""
    items = {}
    for label, value in re.findall(r'(數甲|數乙|數A|數B|國|英|社|自|物|化|生|歷|地|公)\s*x\s*(\d+(?:\.\d+)?)', text):
        key = LABELS[label]
        if key in items:
            raise ValueError('官方採計科目重複')
        weight = float(value)
        if weight <= 0:
            raise ValueError('官方倍率必須為正值')
        items[key] = weight
    return items


def database_weights(row):
    return {key: value for key in LABELS.values()
            if (value := positive(row[key])) is not None}


def compare(row, official, check_weights=False):
    """年度代碼已串接後，比較門檻及選用的逐科採計項。"""
    if official is None:
        return ['missing_official_code']
    issues = []
    if positive(row['結果分數']) != official['ordinary_cutoff']:
        issues.append('ordinary_cutoff')
    if check_weights:
        if official.get('unknown_multipliers', False):
            issues.append('unparsed_subject_multipliers')
        if positive(row['採計術科']) is not None:
            issues.append('unexpected_skill_subject')
        if database_weights(row) != official['weights']:
            issues.append('subject_multipliers')
        if not official['weights']:
            issues.append('empty_subjects')
    return issues


def index_prior(rows):
    """拒絕群組鍵或年度代碼碰撞，避免將同一官方列重複當成兩個校系。"""
    groups, codes = {}, set()
    for row in rows:
        gid = row['dept_group_id']
        if gid in groups:
            raise ValueError('凍結年度群組鍵重複')
        groups[gid] = row
        code = row['學系代碼']
        if code is None or not str(code).strip():
            continue
        normalized = str(code).zfill(4)
        if not re.fullmatch(r'\d{4}', normalized) or normalized in codes:
            raise ValueError('凍結年度代碼格式不合法或重複')
        codes.add(normalized)
    return groups


def parse_pdf(source):
    records = {}
    with pdfplumber.open(source) as pdf:
        pages = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, 1):
            for table in page.extract_tables():
                for row in table:
                    if not row or not re.fullmatch(r'\d{4}', row[0] or ''):
                        continue
                    if len(row) != 12 or row[0] in records:
                        raise ValueError('官方欄位位移或年度代碼重複')
                    text = row[3] or ''
                    weights = parse_weights(text)
                    records[row[0]] = {'ordinary_cutoff': positive(row[5]),
                                      'weights': weights,
                                      'unknown_multipliers': len(re.findall(r'x\s*\d+(?:\.\d+)?', text)) != len(weights),
                                      'page': page_number}
    return records, pages


def main():
    manifest = json.loads((PAPER / 'data/manifest.json').read_text())
    raw = frozen_database_bytes()
    source = PAPER / 'sources/official/114_result_school_data.pdf'
    records, pages = parse_pdf(source)
    database = sqlite3.connect(':memory:')
    database.deserialize(raw)
    database.execute('PRAGMA query_only=ON')
    database.row_factory = sqlite3.Row
    prior = database.execute('SELECT * FROM ast_data WHERE D_datayear=2025').fetchall()
    groups = index_prior(prior)
    with (PAPER / 'data/department-benchmark.csv').open(newline='') as handle:
        benchmark = list(csv.DictReader(handle))
    baseline_groups = {int(row['gid']) for row in benchmark if row['baseline'].strip()}
    if not baseline_groups or baseline_groups - groups.keys():
        raise ValueError('歷史基準缺少對應年度資料')
    checked, unavailable, mismatches, baseline_rows = [], [], [], []
    for gid, row in groups.items():
        code = row['學系代碼']
        if code is None or not str(code).strip():
            unavailable.append({'gid': gid, 'has_skill_subject': positive(row['採計術科']) is not None,
                                'used_by_baseline': gid in baseline_groups})
            if gid in baseline_groups:
                raise ValueError('歷史基準使用缺少年度代碼的資料')
            continue
        code = str(code).zfill(4)
        if not re.fullmatch(r'\d{4}', code):
            raise ValueError('凍結年度代碼格式不合法')
        official = records.get(code)
        issues = compare(row, official, gid in baseline_groups)
        if issues:
            mismatches.append({'gid': gid, 'code': code, 'issues': issues})
        entry = {'gid': gid, 'code': code, 'page': official['page'] if official else None,
                 'ordinary_cutoff': positive(row['結果分數']),
                 'official_cutoff': official['ordinary_cutoff'] if official else None,
                 'used_by_baseline': gid in baseline_groups, 'issues': ';'.join(issues)}
        checked.append(entry)
        if gid in baseline_groups:
            if positive(row['結果分數']) is None:
                raise ValueError('歷史基準使用非正值門檻')
            baseline_rows.append({'gid': gid, 'code': code, 'page': official['page'],
                                  'ordinary_cutoff': official['ordinary_cutoff'],
                                  'subject_multipliers': official['weights']})
    database.close()
    target = PAPER / 'data/historical-cutoff-audit.csv'
    with target.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(checked[0]))
        writer.writeheader()
        writer.writerows(sorted(checked, key=lambda r:r['gid']))
    summary = {'checkedAt': datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat(), 'version': 'v0.10', 'year': 2025,
               'url': 'https://www.uac.edu.tw/114data/114_result_school_data.pdf',
               'pdfSHA256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'pages': pages, 'officialRowsParsed': len(records), 'frozenRows': len(prior),
               'cutoffRowsChecked': len(checked), 'baselineRowsChecked': len(baseline_rows),
               'unavailableAnnualCodes': unavailable, 'mismatches': mismatches,
               'baselineInputs': sorted(baseline_rows, key=lambda r:r['gid']),
               'auditCSV_SHA256': hashlib.sha256(target.read_bytes()).hexdigest(),
               'scope': '核對 2025 年年度代碼下的普通生門檻，並逐科核對歷史基準所用的採計倍率；不驗證跨年群組的實際課程等同性、容量、部署或獨立年度預測效度。'}
    (PAPER / 'data/historical-cutoff-audit.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='baselineInputs'},ensure_ascii=False))
    if mismatches:
        raise ValueError('官方歷史來源與凍結 DB 不一致，保留差異後停止')


if __name__ == '__main__':
    main()
