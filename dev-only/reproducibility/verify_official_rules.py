"""Check subject multipliers and admitted counts against the official 2026 outcome table.

Reads the official table (UAC 2026b, 115_result_school_data.pdf), the department codes of
data/official-truth-audit.csv, the 2026 subject rules of data/baseline-inputs.json and the
quotas of data/department-benchmark.csv. For every evaluated department it compares each
subject's multiplier, records the admitted count (including supernumerary places) and whether
the table lists tie-breaking values at the ordinary cutoff. Writes data/official-rules-audit.csv
and data/official-rules-audit.json. Public data only; no candidate records.

Usage: python3 verify_official_rules.py path/to/115_result_school_data.pdf
"""
import csv
import hashlib
import io
import json
import re
import sys
from pathlib import Path

import pdfplumber

PAPER = Path(__file__).resolve().parents[2]
SUBJECTS = {'國': 'gsat_chinese', '英': 'gsat_english', '數A': 'gsat_mathA', '數B': 'gsat_mathB',
            '自': 'gsat_science', '社': 'gsat_society', '數甲': 'ast_mathA', '數乙': 'ast_mathB',
            '物': 'ast_physics', '化': 'ast_chemistry', '生': 'ast_biology', '歷': 'ast_history',
            '地': 'ast_geography', '公': 'ast_civics', '術': 'skill'}


def parse(pdf_path):
    records = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if not row or not re.fullmatch(r'\d{4}', row[0] or ''):
                        continue
                    if len(row) != 12 or row[0] in records:
                        raise ValueError('unexpected table layout')
                    weights = [(SUBJECTS[a], float(w)) for a, w in re.findall(r'([^\sx\d.]+)x(\d+(?:\.\d+)?)', row[3] or '')]
                    tie = (row[6] or '').strip()
                    records[row[0]] = {'weights': sorted(weights), 'admitted': int(row[4]),
                                       'tie': tie, 'raw_tie': bool(re.search(r'\d+\.\d+', tie)),
                                       'skill': any(s == 'skill' for s, _ in weights)}
    return records


def main(pdf_path):
    records = parse(pdf_path)
    codes = {int(r['gid']): r['code'] for r in csv.DictReader((PAPER / 'data/official-truth-audit.csv').open())}
    items = {d['gid']: sorted((i['subject'], float(i['weight'])) for i in d['items'])
             for d in json.loads((PAPER / 'data/baseline-inputs.json').read_text())['departments']}
    quota = {int(r['gid']): int(r['official_quota']) for r in csv.DictReader((PAPER / 'data/department-benchmark.csv').open())}
    rows, mismatches = [], []
    for gid, code in sorted(codes.items()):
        official = records[code]
        match = official['weights'] == items[gid]
        if not match:
            mismatches.append(gid)
        rows.append({'gid': gid, 'code': code, 'admitted_including_extra': official['admitted'],
                     'multipliers_match': match, 'tie_break_recorded': bool(official['tie']),
                     'raw_score_tie_break': official['raw_tie']})
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    (PAPER / 'data/official-rules-audit.csv').write_text(out.getvalue())
    skill = [r for r in records.values() if r['skill']]
    summary = {
        'checkedAt': '2026-11-25', 'url': 'https://www.uac.edu.tw/115data/115_result_school_data.pdf',
        'pdfSHA256': hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest(),
        'officialRows': len(records), 'practicalSkillRows': len(skill),
        'practicalSkillAdmittedIncludingExtra': sum(r['admitted'] for r in skill),
        'nonSkillRows': len(records) - len(skill),
        'evaluatedDepartments': len(rows), 'subjectMultiplierMismatches': len(mismatches),
        'tieBreakRecordedAllRows': sum(bool(r['tie']) for r in records.values()),
        'rawScoreTieBreakAllRows': sum(r['raw_tie'] for r in records.values()),
        'tieBreakRecordedEvaluated': sum(r['tie_break_recorded'] for r in rows),
        'rawScoreTieBreakEvaluated': sum(r['raw_score_tie_break'] for r in rows),
        'evaluatedAdmittedBelowQuota': sum(r['admitted_including_extra'] < quota[r['gid']] for r in rows),
        'evaluatedAdmittedAboveQuota': sum(r['admitted_including_extra'] > quota[r['gid']] for r in rows),
        'note': 'Each subject multiplier of every evaluated department is compared with the frozen 2026 rules. '
                'Admitted counts include supernumerary places, so an admitted count below the quota marks an '
                'underfilled department but a count above it may reflect supernumerary places or ties.',
        'auditCSV_SHA256': hashlib.sha256(out.getvalue().encode()).hexdigest()}
    (PAPER / 'data/official-rules-audit.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: verify_official_rules.py path/to/115_result_school_data.pdf')
    main(sys.argv[1])
