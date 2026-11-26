"""Exact-table conversions of last year's cutoff (exploratory; added after a pre-submission review).

For departments whose multipliers are all equal in both years and whose subject combination did
not change, the weighted total is a multiple of the unweighted total, whose distribution the
official combination tables give exactly. On those departments we compare the paper's baseline
(comonotonic approximation, percentile ranks, General Scholastic Ability Test grades times four)
with two exact conversions: equal percentile rank and equal number of examinees at or above the
cutoff, the rule commonly used by placement services. The same conversions applied to 2024
cutoffs predict 2025 cutoffs, a backtest of their level bias. Writes data/practice-baseline.json.
"""
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, load_rows, common_rows, output_path  # noqa: E402
from history_checks import cluster_interval  # noqa: E402

LAMBDA = 0.4


def combo_key(items):
    return '+'.join(sorted('ast_' + i['subject'] if i['subject'].startswith('gsat') else i['subject'] for i in items))


def interpolate(xs, ys, x):
    """Piecewise-linear y(x) for increasing xs; clamps outside."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for (x0, y0), (x1, y1) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return ys[-1]


def position(table, total, by):
    """Mid-point percentile rank (by='pr') or examinees at or above (by='count') at a total."""
    levels = [r['level'] for r in table]
    n = table[-1]['cum_below']
    if by == 'pr':
        values = [(r['cum_below'] - r['people'] / 2) / n * 100 for r in table]
    else:
        values = [r['cum_above'] - r['people'] / 2 for r in table]
    return interpolate(levels, values, total)


def total_at(table, value, by):
    """Inverse of position(); counts decrease with the level, so search on the reversed table."""
    levels = [r['level'] for r in table]
    n = table[-1]['cum_below']
    if by == 'pr':
        values = [(r['cum_below'] - r['people'] / 2) / n * 100 for r in table]
        return interpolate(values, levels, value)
    values = [r['cum_above'] - r['people'] / 2 for r in table]
    return interpolate(values[::-1], levels[::-1], value)


def convert(cutoff, old_items, new_items, old_year, new_year, tables, by):
    m_old = old_items[0]['weight']
    m_new = new_items[0]['weight']
    t_old, t_new = tables.get(f'{old_year}:{combo_key(old_items)}'), tables.get(f'{new_year}:{combo_key(new_items)}')
    if t_old is None or t_new is None:
        return None
    return m_new * total_at(t_new, position(t_old, cutoff / m_old, by), by)


def eligible(old_items, new_items):
    return (old_items and new_items and len({i['weight'] for i in old_items}) == 1
            and len({i['weight'] for i in new_items}) == 1 and combo_key(old_items) == combo_key(new_items))


def main():
    tables = json.loads((PAPER / 'data/combination-tables.json').read_text())['tables']
    frozen = {d['gid']: d for d in json.loads((PAPER / 'data/baseline-inputs.json').read_text())['departments']}
    older = {d['gid']: d['prior2024'] for d in json.loads((PAPER / 'data/history-inputs.json').read_text())['departments']}
    with (PAPER / 'data/history-2024.csv').open(newline='') as f:
        hist = {int(r['gid']): r for r in csv.DictReader(f)}
    rows = load_rows()
    j2 = common_rows(rows, ('v3', 'baseline'))

    sub = []
    for r in j2:
        d = frozen[r['gid']]
        prior = d['prior']
        if prior is None or prior['cutoff'] is None or not eligible(prior['items'], d['items']):
            continue
        pr = convert(prior['cutoff'], prior['items'], d['items'], 2025, 2026, tables, 'pr')
        count = convert(prior['cutoff'], prior['items'], d['items'], 2025, 2026, tables, 'count')
        if pr is None or count is None:
            continue
        sub.append(dict(r, exact_pr=pr, exact_count=count,
                        mix=LAMBDA * r['v3'] + (1 - LAMBDA) * r['baseline'],
                        mix_count=LAMBDA * r['v3'] + (1 - LAMBDA) * count))
    e = lambda r, k: (r[k] - r['actual']) / r['weightTotal']
    mae = lambda rows_, k: statistics.fmean(abs(e(r, k)) for r in rows_)
    bias = lambda rows_, k: statistics.fmean(e(r, k) for r in rows_)
    diff = lambda rows_, a, b: statistics.fmean(abs(e(r, a)) - abs(e(r, b)) for r in rows_)
    keys = ('baseline', 'exact_pr', 'exact_count', 'v3', 'mix', 'mix_count')
    out = {'note': 'exploratory; added after a pre-submission review', 'n': len(sub),
           'schools': len({r['school'] for r in sub}),
           'mae': {k: mae(sub, k) for k in keys}, 'bias': {k: bias(sub, k) for k in keys},
           'exact_count_minus_baseline': {'difference': diff(sub, 'exact_count', 'baseline'),
                                          'interval': cluster_interval(sub, lambda s: diff(s, 'exact_count', 'baseline'))},
           'mix_count_minus_exact_count': {'difference': diff(sub, 'mix_count', 'exact_count'),
                                           'relative': diff(sub, 'mix_count', 'exact_count') / mae(sub, 'exact_count'),
                                           'interval': cluster_interval(sub, lambda s: diff(s, 'mix_count', 'exact_count'))},
           # How far the comonotonic approximation moves the converted cutoff where the composite is unchanged.
           'mean_abs_baseline_minus_exact_pr': statistics.fmean(abs(r['baseline'] - r['exact_pr']) / r['weightTotal'] for r in sub),
           'max_abs_baseline_minus_exact_pr': max(abs(r['baseline'] - r['exact_pr']) / r['weightTotal'] for r in sub)}

    # Backtest: the same conversions from 2024 to 2025.
    back = {'comonotonic': [], 'pr': [], 'count': []}
    for gid, h in hist.items():
        o, d = older.get(gid), frozen[gid]['prior']
        if o is None or d is None or o['cutoff'] is None or o['hasSkill'] or d['cutoff'] is None or d['hasSkill']:
            continue
        if not eligible(o['items'], d['items']):
            continue
        total_2025 = sum(i['weight'] for i in d['items'])
        if h['b25'] in ('', 'None'):
            continue
        back['comonotonic'].append((float(h['b25']) - d['cutoff']) / total_2025)
        for by in ('pr', 'count'):
            p = convert(o['cutoff'], o['items'], d['items'], 2024, 2025, tables, by)
            if p is not None:
                back[by].append((p - d['cutoff']) / total_2025)
    out['backtest_2025'] = {by: {'n': len(v), 'bias': statistics.fmean(v), 'mae': statistics.fmean(abs(x) for x in v)}
                            for by, v in back.items()}
    output_path('practice-baseline.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
