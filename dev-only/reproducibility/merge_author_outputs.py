"""Merge the section outputs of author_checks.mjs and author_stats.py into the released aggregate files.

Reads OUT_DIR/author-checks-*.json and OUT_DIR/author-stats-*.json, keeps full precision, stores each distinct
provenance record (platform commit and uncommitted changes, every loaded platform file with its SHA-256, runtime
versions, and the hashes of the export, the frozen aggregate source, the released department file and the two
scripts) once with the sections it covers, adds the SHA-256 of the Python scripts used by author_stats.py, and
writes DEST_DIR/author-checks.json, DEST_DIR/author-stats.json and DEST_DIR/bootstrap-summary.json (the H6 section,
under the file name that plan v0.22 gives). Department-level values never enter these files.

Usage: OUT_DIR=... DEST_DIR=... python3 merge_author_outputs.py
"""
import hashlib
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAPER = HERE.parents[1]
OUT = Path(os.environ.get('OUT_DIR', PAPER / 'out'))
DEST = Path(os.environ.get('DEST_DIR', PAPER / 'data'))
STATS_SCRIPTS = ('author_stats.py', 'analyze.py', 'decision_checks.py', 'robustness_checks.py', 'history_checks.py',
                 'demand_signal.py', 'exploratory_checks.py', 'reproduce_baseline.py')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    checks = {'note': ("Aggregates of the record-level author checks (plan dev-only/review/analysis-plan-v022.md and the "
                       "exploratory additions listed in Supplement S15), computed on the author's computer from a "
                       "pseudonymized export that was deleted after the analyses; full precision."),
              'provenance': [], 'sections': {}}
    groups = {}
    for path in sorted(OUT.glob('author-checks-*.json')):
        data = json.loads(path.read_text())
        record = {'provenance': data.pop('provenance', None), 'inputs': data.pop('inputs', None)}
        key = json.dumps(record, sort_keys=True)
        groups.setdefault(key, dict(record, sections=[]))['sections'].append(data['section'])
        checks['sections'][data['section']] = data
    checks['provenance'] = list(groups.values())
    stats = {'note': ("Statistics on the released J2 set (1,521 departments) with each rerun's v3 values in place of the "
                      "evaluated ones; the reruns' department values are not released; full precision."),
             'scripts': {name: sha256(HERE / name) for name in STATS_SCRIPTS}, 'groups': {}}
    for path in sorted(OUT.glob('author-stats-*.json')):
        data = json.loads(path.read_text())
        stats['groups'][data['group']] = data
    if not checks['sections'] or not stats['groups']:
        raise SystemExit('no section outputs found in ' + str(OUT))
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / 'author-checks.json').write_text(json.dumps(checks, indent=1, ensure_ascii=False) + '\n')
    (DEST / 'author-stats.json').write_text(json.dumps(stats, indent=1, ensure_ascii=False) + '\n')
    if 'bootstrap' in checks['sections']:
        boot = dict(checks['sections']['bootstrap'])
        boot['copyOf'] = 'the bootstrap section of author-checks.json, under the file name that plan v0.22 gives'
        (DEST / 'bootstrap-summary.json').write_text(json.dumps(boot, indent=1, ensure_ascii=False) + '\n')
    print(json.dumps({'sections': sorted(checks['sections']), 'groups': sorted(stats['groups']),
                      'provenanceRecords': len(checks['provenance'])}))


if __name__ == '__main__':
    main()
