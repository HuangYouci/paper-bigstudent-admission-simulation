"""核對大考中心公開 XLS 與凍結資料庫；轉檔只存於忽略工作區。"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import sys
import math
import os
import shutil
import sqlite3
import subprocess
from openpyxl import load_workbook

PAPER = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from frozen_db import frozen_database_bytes  # noqa: E402
# LibreOffice converts the official XLS files; set SOFFICE to its executable if it is not on PATH.
SOFFICE = os.environ.get('SOFFICE') or shutil.which('soffice') or 'soffice'
LABELS = {'數學甲': 'ast_mathA', '數學乙': 'ast_mathB', '化學': 'ast_chemistry',
          '物理': 'ast_physics', '生物': 'ast_biology', '歷史': 'ast_history',
          '地理': 'ast_geography', '公民與社會': 'ast_civics',
          '國文': 'ast_gsat_chinese', '英文': 'ast_gsat_english',
          '數學A': 'ast_gsat_mathA', '數學B': 'ast_gsat_mathB',
          '社會': 'ast_gsat_society', '自然': 'ast_gsat_science'}


def parse_rows(rows):
    """依官方表頭解析兩個並排科目，每科必須完整涵蓋 0–60 級分。"""
    values = {}
    subjects = None
    for row in rows:
        if str(row[0]).strip() == '級分':
            subjects = [(LABELS[str(row[col]).strip()], col) for col in (1, 7)]
            continue
        level = str(row[0]).strip()
        if not subjects or not level.isdigit() or not 0 <= int(level) <= 60:
            continue
        for subject, col in subjects:
            count = row[col]
            if type(count) not in (int, float) or not math.isfinite(count) or int(count) != count or count < 0:
                raise ValueError('官方級分人數格式不符')
            key = (subject, int(level))
            if key in values:
                raise ValueError('官方級分列重複')
            values[key] = int(count)
    return values


def main():
    parser = argparse.ArgumentParser(description='核對官方逐級分人數與凍結招生資料庫')
    parser.add_argument('--year', type=int, choices=(2025, 2026), default=2026)
    year = parser.parse_args().year
    academic_year = year - 1911
    output_prefix = 'official-marginal-audit' if year == 2026 else 'historical-marginal-audit'
    manifest = json.loads((PAPER / 'data/manifest.json').read_text())
    raw = frozen_database_bytes()
    database = sqlite3.connect(':memory:')
    database.deserialize(raw)
    database.execute('PRAGMA query_only=ON')
    workspace = PAPER / 'dev-only/workspace/xls-convert'
    workspace.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    for key in ('TMPDIR', 'TEMP', 'TMP'):
        environment[key] = str(workspace)
    sources = [PAPER / 'sources/official' / name for name in
               (f'{academic_year}_ast_score_distribution.xls', f'{academic_year}_gsat_admission_distribution.xls')]
    official = {}
    source_hashes = {}
    for source in sources:
        source_hashes[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
        target = workspace / (source.stem + '.xlsx')
        if not target.exists():
            subprocess.run([SOFFICE,
                            '-env:UserInstallation=' + (workspace / 'profile').as_uri(),
                            '--headless', '--convert-to', 'xlsx', '--outdir', str(workspace), str(source)],
                           env=environment, capture_output=True, check=True, timeout=90)
        workbook = load_workbook(target, read_only=True, data_only=True)
        parsed = parse_rows(workbook.worksheets[0].iter_rows(max_col=14, values_only=True))
        if set(official).intersection(parsed):
            raise ValueError('不同官方檔案含重複科目')
        official.update(parsed)
        workbook.close()
    expected = {(s, level) for s in LABELS.values() for level in range(61)}
    if set(official) != expected:
        raise ValueError('14 科 × 61 級分來源不完整')
    mismatch = []
    rows = []
    for (subject, level), count in official.items():
        stored = database.execute('SELECT people FROM score_distribution WHERE D_datayear=? AND subjects=? AND level=?',
                                  (year, subject, level)).fetchone()
        if stored is None or stored[0] != count:
            mismatch.append({'subject': subject, 'level': level, 'official': count, 'frozen': stored[0] if stored else None})
    for subject in sorted(LABELS.values()):
        for lo, hi in ((0, 19), (20, 39), (40, 60)):
            total = sum(official[subject, level] for level in range(lo, hi + 1))
            stored = database.execute('SELECT SUM(people) FROM score_distribution WHERE D_datayear=? AND subjects=? AND level BETWEEN ? AND ?',
                                      (year, subject, lo, hi)).fetchone()[0]
            rows.append({'subject': subject, 'lower': lo, 'upper': hi, 'official_count': total,
                         'frozen_count': stored, 'difference': stored - total})
    with (PAPER / ('data/' + output_prefix + '.csv')).open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    output = {'checkedAt': '2026-10-08', 'year': year, 'sourceSHA256': source_hashes, 'subjects': 14,
              'levelsChecked': len(official), 'bandsChecked': len(rows), 'levelMismatches': mismatch,
              'bandMismatches': sum(r['difference'] != 0 for r in rows),
              'scope': '官方人數與凍結目標一致性，不證明正式登記人口代表性或自選偏好代表性。'}
    (PAPER / ('data/' + output_prefix + '.json')).write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(output, ensure_ascii=False))
    if mismatch or output['bandMismatches']:
        raise ValueError('官方目標與凍結資料庫不一致，請保留差異並查核')


if __name__ == '__main__':
    main()
