"""Build the two-year history inputs from public admission data (no candidate records).

Reads the platform's public-data SQLite archive (official cutoffs, quotas, subject rules and
score distributions for 2024-2026), checks that its 2025 and 2026 entries equal the frozen
inputs of the historical baseline, and writes data/history-inputs.json and
data/history-2024.csv:

* H24: the 2024 cutoff converted to the 2026 scale with the baseline's own method;
* B25: the 2024 cutoff converted to the 2025 scale, a backtest of the baseline method on 2025;
* official quotas for 2024-2026.

Usage: python3 prepare_history.py --database path/to/database.db
"""
import argparse
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from reproduce_baseline import curve, weighted_pr, weighted_score

PAPER = Path(__file__).resolve().parents[2]
AST = {'採計數學甲': 'ast_mathA', '採計數學乙': 'ast_mathB', '採計物理': 'ast_physics', '採計化學': 'ast_chemistry',
       '採計生物': 'ast_biology', '採計歷史': 'ast_history', '採計地理': 'ast_geography', '採計公民': 'ast_civics'}
GSAT = {'採計國文': 'gsat_chinese', '採計英文': 'gsat_english', '採計數學A': 'gsat_mathA', '採計數學B': 'gsat_mathB',
        '採計社會': 'gsat_society', '採計自然': 'gsat_science'}


def number(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def items_of(row):
    items = []
    for column, subject in list(GSAT.items()) + list(AST.items()):
        weight = number(row.get(column))
        if weight and weight > 0:
            items.append({'subject': subject, 'kind': 'gsat60' if subject.startswith('gsat') else 'ast', 'weight': weight})
    return sorted(items, key=lambda i: i['subject'])


def has_skill(row):
    return number(row.get('採計術科')) not in (None, 0.0)


def load(database):
    con = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    rows = {}
    for r in con.execute('select * from ast_data where D_datayear in (2024, 2025, 2026)'):
        r = dict(r)
        key = (int(r['D_datayear']), int(r['dept_group_id']))
        if key in rows:
            raise ValueError(f'duplicate row {key}')
        rows[key] = r
    distributions = {}
    for r in con.execute("select D_datayear, subjects, level, people, cum_below from score_distribution "
                         "where D_datayear in (2024, 2025, 2026) and subjects not like '%+%' order by D_datayear, subjects, level"):
        distributions.setdefault(f"{r['D_datayear']}:{r['subjects']}", []).append(
            {'level': r['level'], 'people': r['people'], 'cum_below': r['cum_below']})
    return rows, distributions


def same_items(a, b):
    key = lambda items: sorted((i['subject'], i['kind'], round(float(i['weight']), 6)) for i in items)
    return key(a) == key(b)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', required=True, type=Path)
    args = parser.parse_args()
    frozen = json.loads((PAPER / 'data/baseline-inputs.json').read_text())
    rows, raw = load(args.database)

    # 1. The archive must reproduce the frozen 2025/2026 inputs exactly.
    for key, value in frozen['distributions'].items():
        if raw.get(key) != value:
            raise ValueError(f'distribution {key} differs from the frozen baseline inputs')
    positive = lambda value: value if value is not None and value > 0 else None
    mismatches = []
    for d in frozen['departments']:
        r25, r26 = rows.get((2025, d['gid'])), rows.get((2026, d['gid']))
        if r26 is None or not same_items(items_of(r26), d['items']):
            mismatches.append((d['gid'], '2026 items'))
        if d['prior'] is not None:
            if r25 is None or positive(number(r25['結果分數'])) != positive(d['prior']['cutoff']) \
                    or not same_items(items_of(r25), d['prior']['items']):
                mismatches.append((d['gid'], '2025 prior'))
    # The archive moved one department's 2025 entry after the baseline was frozen (10 October 2026).
    unexpected = [m for m in mismatches if m != (934, '2025 prior')]
    if unexpected:
        raise ValueError(f'{len(unexpected)} departments differ from the frozen inputs, e.g. {unexpected[:5]}')

    distributions = {k: curve(v) for k, v in raw.items()}
    out_rows, departments = [], []
    for d in frozen['departments']:
        gid = d['gid']
        r24, r25, r26 = rows.get((2024, gid)), rows.get((2025, gid)), rows.get((2026, gid))
        record = {'gid': gid, 'quota_2024': None, 'quota_2025': None, 'quota_2026': None,
                  'cutoff_2024': None, 'cutoff_2025': None, 'weight_total_2025': None,
                  'h24': None, 'b25': None, 'rules_changed_2024_2025': None, 'relinked_baseline': None}
        for year, r in ((2024, r24), (2025, r25), (2026, r26)):
            if r is not None:
                record[f'quota_{year}'] = r['總名額']
        if r25 is not None:
            record['cutoff_2025'] = number(r25['結果分數'])
            record['weight_total_2025'] = sum(i['weight'] for i in items_of(r25))
            # The frozen archive treated some renamed or recoded departments as new; the later
            # archive links them to a 2025 predecessor. Their baseline is computed with the same
            # method for a sensitivity analysis only; the frozen baseline is not changed.
            c25 = positive(record['cutoff_2025'])
            if d['prior'] is None and c25 is not None and items_of(r25) and not has_skill(r25):
                pr = weighted_pr(items_of(r25), 2025, c25, distributions)
                if pr is not None:
                    record['relinked_baseline'] = weighted_score(d['items'], 2026, pr, distributions)
        if r24 is not None:
            c24 = number(r24['結果分數'])
            record['cutoff_2024'] = c24 if c24 and c24 > 0 else None
            usable = record['cutoff_2024'] is not None and not has_skill(r24) and items_of(r24)
            if usable:
                pr = weighted_pr(items_of(r24), 2024, record['cutoff_2024'], distributions)
                if pr is not None:
                    record['h24'] = weighted_score(d['items'], 2026, pr, distributions)
                    if r25 is not None and items_of(r25) and not has_skill(r25):
                        record['b25'] = weighted_score(items_of(r25), 2025, pr, distributions)
            if r25 is not None:
                record['rules_changed_2024_2025'] = not same_items(items_of(r24), items_of(r25))
        out_rows.append(record)
        departments.append({'gid': gid, 'prior2024': None if r24 is None else {
            'cutoff': record['cutoff_2024'], 'hasSkill': has_skill(r24), 'items': items_of(r24)}})

    inputs = {'recordDate': '2026-11-25',
              'scope': 'Public official cutoffs, quotas, subject rules and score distributions for 2024-2026; no candidate records.',
              'archiveSHA256': hashlib.sha256(args.database.read_bytes()).hexdigest(),
              'check': 'The archive reproduces every 2025 and 2026 entry of data/baseline-inputs.json, except that '
                       'department 934 no longer has a 2025 entry; its frozen 2025 cutoff is kept by the baseline.',
              'distributions2024': {k: v for k, v in raw.items() if k.startswith('2024:')},
              'departments': departments}
    (PAPER / 'data/history-inputs.json').write_text(json.dumps(inputs, ensure_ascii=False, separators=(',', ':')) + '\n')

    # Official distributions of unweighted totals for subject combinations, kept for departments
    # whose multipliers are all equal (their weighted total is a multiple of the unweighted one).
    def combo_key(items):
        return '+'.join(sorted('ast_' + i['subject'] if i['subject'].startswith('gsat') else i['subject'] for i in items))
    needed = set()
    for (year, gid), r in rows.items():
        items = items_of(r)
        if items and len({i['weight'] for i in items}) == 1:
            needed.add((year, combo_key(items)))
    con = sqlite3.connect(f'file:{args.database}?mode=ro', uri=True)
    tables = {}
    for year, key in sorted(needed):
        got = con.execute('select level, people, cum_above, cum_below from score_distribution '
                          'where D_datayear = ? and subjects = ? order by level', (year, key)).fetchall()
        if got:
            tables[f'{year}:{key}'] = [{'level': a, 'people': b, 'cum_above': c, 'cum_below': d} for a, b, c, d in got]
    (PAPER / 'data/combination-tables.json').write_text(json.dumps(
        {'scope': 'Official cumulative tables of unweighted totals by subject combination (UAC), 2024-2026, '
                  'for combinations used by departments whose multipliers are all equal.',
         'tables': tables}, ensure_ascii=False, separators=(',', ':')) + '\n')
    with (PAPER / 'data/history-2024.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        writer.writeheader()
        writer.writerows(out_rows)
    print(json.dumps({'departments': len(out_rows), 'h24': sum(r['h24'] is not None for r in out_rows),
                      'b25': sum(r['b25'] is not None for r in out_rows)}))


if __name__ == '__main__':
    main()
