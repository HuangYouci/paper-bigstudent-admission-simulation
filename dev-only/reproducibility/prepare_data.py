"""由封存校系資料與唯讀 Git 物件重建論文資料，不存取雲端帳號。"""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess

PAPER = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description='唯讀擷取歷史招生資料並重建校系研究資料')
    parser.add_argument('--repository', required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads((PAPER / 'data/manifest.json').read_text())
    snapshot_path = PAPER / 'sources/benchmark-snapshot.md'
    comparison_path = PAPER / 'sources/compare-depts.csv'
    if hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != manifest['aggregateSourceSHA256']:
        raise ValueError('封存校系來源雜湊不符')
    if hashlib.sha256(comparison_path.read_bytes()).hexdigest() != manifest['comparisonSourceSHA256']:
        raise ValueError('封存比較表雜湊不符')
    snapshot = json.loads(snapshot_path.read_text().split('```json\n', 1)[1].split('\n```', 1)[0])
    raw = subprocess.check_output(['git', 'show', manifest['verifiableResearchCommit'] + ':lib/database.db'], cwd=args.repository)
    if hashlib.sha256(raw).hexdigest() != manifest['sourceHashes']['lib/database.db']:
        raise ValueError('歷史資料庫雜湊不符')
    connection = sqlite3.connect(':memory:')
    connection.deserialize(raw)
    connection.execute('PRAGMA query_only=ON')
    with comparison_path.open(encoding='utf-8', newline='') as handle:
        saved_rows = list(csv.DictReader(handle))
    saved = {int(row['dept_group_id']): row for row in saved_rows}
    if len(saved) != len(saved_rows):
        raise ValueError('封存比較表有重複校系')
    fields = ['gid', 'school', 'department', 'actual', 'weightTotal', 'v1', 'v2', 'fractional', 'v3', 'baseline', 'unchangedWeights', 'archived_v3', 'official_quota', 'applicant_count', 'confidence', 'quota_status', 'prior_record_count', 'prior_positive_cutoff_count', 'prior_2025_positive_cutoff', 'no_history_in_snapshot']
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in snapshot['rows']:
        saved_row = saved[row['gid']]
        if abs(float(saved_row['official_cutoff']) - row['actual']) > 1e-8:
            raise ValueError('官方門檻來源不一致')
        prior = connection.execute('SELECT D_datayear,結果分數 FROM ast_data WHERE dept_group_id=? AND D_datayear<2026', (row['gid'],)).fetchall()
        valid = [(year, float(value)) for year, value in prior if value is not None and str(value).strip() and float(value) > 0]
        writer.writerow({**row, 'department': saved_row['dept'], 'archived_v3': saved_row['sim_published_cutoff'],
                         'official_quota': saved_row['official_quota'], 'applicant_count': saved_row['applicant_count'],
                         'confidence': saved_row['confidence'], 'quota_status': saved_row['quota_status'],
                         'prior_record_count': len(prior), 'prior_positive_cutoff_count': len(valid),
                         'prior_2025_positive_cutoff': next((value for year, value in valid if int(year) == 2025), None),
                         'no_history_in_snapshot': not valid})
    output = buffer.getvalue().encode('utf-8')
    # The full file is private; its hash is kept by the author (FULL_HASHES_JSON), not in the package.
    expected = json.loads(Path(os.environ['FULL_HASHES_JSON']).read_text())['department-benchmarkFullSHA256']
    if hashlib.sha256(output).hexdigest() != expected:
        raise ValueError('重建結果與凍結研究資料不一致，停止覆寫')
    (Path(os.environ['FULL_OUTPUT_DIR']) / 'department-benchmark-full.csv').write_bytes(output)
    print('校系完整資料逐位元重建一致：1,706 系；釋出檔由 suppress_small_cells.py 產生。')


if __name__ == '__main__':
    main()
