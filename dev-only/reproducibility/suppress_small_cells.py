"""Write the released department files from the full ones (author-side tool).

A simulated cutoff is an order statistic: every v1, v2 and Fractional cutoff, and the v3 cutoff of
an underfilled department, equals the weighted score of one record. The released files therefore
  1. withhold every simulated value, and the simulated filling status, of a department with fewer
     than five platform listings (department-benchmark.csv, weighting-granularity-departments.csv);
  2. round every released simulated value to two decimals, as the platform itself displays them;
  3. leave out the department values of the earlier saved runs, whose listing counts were not
     saved; run-level summaries computed without the withheld departments are released instead
     (archived_run_summary.py).
Official values, the historical baseline and listing counts are kept. Every statistic reported in
the manuscript and supplement is computed from the released files. The hashes of the full files
are written to a private file for the editor, not to the package.

Usage: python3 suppress_small_cells.py --full-dir DIR --private-out FILE
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

PAPER = Path(__file__).resolve().parents[2]
K = 5
SIMULATED = ('v1', 'v2', 'fractional', 'v3', 'archived_v3')
STATUS = ('quota_status',)


def read(path):
    with path.open(encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def write(path, fields, rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def two_decimals(value):
    return value if value == '' else f'{float(value):.2f}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--full-dir', required=True, type=Path)
    parser.add_argument('--private-out', required=True, type=Path)
    args = parser.parse_args()
    fields, bench = read(args.full_dir / 'department-benchmark-full.csv')
    listings = {r['gid']: int(r['applicant_count']) for r in bench}
    small = {gid for gid, n in listings.items() if n < K}
    withheld = rounded = 0
    for r in bench:
        for key in SIMULATED + STATUS:
            if r['gid'] in small:
                withheld += r[key] != ''
                r[key] = ''
            elif key in SIMULATED and r[key] != '':
                rounded += two_decimals(r[key]) != r[key]
                r[key] = two_decimals(r[key])
    report = {'rule': f'simulated values and filling status withheld when platform listings < {K}; '
                      'released simulated values rounded to two decimals; department values of earlier '
                      'saved runs not released',
              'departments': len(small), 'benchmarkValuesWithheld': withheld}
    report['departmentCsvSHA256'] = write(PAPER / 'data/department-benchmark.csv', fields, bench)

    fields, gran = read(args.full_dir / 'weighting-granularity-departments-full.csv')
    count = 0
    for r in gran:
        for key in fields[1:]:
            if r['gid'] in small:
                count += r[key] != ''
                r[key] = ''
            else:
                r[key] = two_decimals(r[key])
    report['granularityValuesWithheld'] = count
    report['granularityCsvSHA256'] = write(PAPER / 'data/weighting-granularity-departments.csv', fields, gran)
    stale = PAPER / 'data/archived-run-cutoffs.csv'
    if stale.exists():
        stale.unlink()
    (PAPER / 'data/suppression.json').write_text(json.dumps(report, indent=2) + '\n')

    private = {'note': 'SHA-256 of the full files, for the editor; not part of the released package'}
    for name in ('department-benchmark', 'weighting-granularity-departments', 'archived-run-cutoffs'):
        private[name + 'FullSHA256'] = hashlib.sha256((args.full_dir / f'{name}-full.csv').read_bytes()).hexdigest()
    args.private_out.write_text(json.dumps(private, indent=2) + '\n')
    print(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
