"""Department-level checks added after the seventh round of simulated reviews (exploratory; no record-level data).

Reads department-benchmark.csv and engine-2026.csv (both controlled-tier files: the public tier withholds the values
these checks need at 118 departments), history-2024.csv, baseline-inputs.json, history-inputs.json, and the stored
aggregates author-checks.json. Intervals resample institutions 4,000 times with the seed of the main text; pointwise
and simultaneous intervals for a family of groups come from the same resamples.

  quota_adjusted   history adjusted for the announced 2026 quota change, with a slope fitted on the 2024->2025 backtest
                   (ex ante; no intercept is carried forward), and the combinations measured against it;
  engine           the reconstructed production engine (engine-2026.csv) and the combinations measured against it;
  table5           the groups of Table 5 against the baseline, the engine and the quota-adjusted history, with shares of
                   the gain and simultaneous (sup-t) intervals;
  table6           the rows of Table 6 against the same three comparators;
  q_reference      direction agreement of the quota-implied departure, and of S on its flags;
  older_history    S and the older history on the same departments, with a paired interval;
  fractional       the combination with Fractional in place of v3, and with Fractional's departures centered;
  transport        the gains of the groups reweighted to the 2024->2025 composition of rule and quota changes;
  shift_by_group   the gain by group if every error moved by the same amount (a shift common to the year);
  decision_time    the saved runs' gains weighted by daily completions, using only runs finished before each day began;
  multiplicity     bootstrap p-values for the subgroup gains of Tables 5 and 6, with Holm and Benjamini-Hochberg
                   adjustment.
Writes seventh-review.json.
"""
import csv
import json
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, common_rows, input_path, load_rows, output_path  # noqa: E402
from history_checks import REPS, load_history  # noqa: E402
from revision_checks import LAMBDA, SEED, errors, mean, public, region_of  # noqa: E402
from robustness_checks import rule_change  # noqa: E402

DAY_SHARE = (('2026-08-05', 0.1056), ('2026-08-06', 0.1420), ('2026-08-07', 0.3380), ('2026-08-08', 0.4144))  # UAC (2026a)
# Saved runs before the deadline, by Taiwan completion time.
RUNS = (('ast_20260805T175904Z', '2026-08-06 01:59'), ('ast_20260806T120005Z', '2026-08-06 20:00'),
        ('ast_20260807T022008Z', '2026-08-07 10:20'), ('ast_20260807T120012Z', '2026-08-07 20:00'),
        ('ast_20260808T035958Z', '2026-08-08 11:59'))
EVALUATED = 'ast_20260815T150000Z'


def ols(xs, ys):
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def lad(xs, ys, iterations=200):
    a, b = ols(xs, ys)
    for _ in range(iterations):
        w = [1 / max(abs(y - a - b * x), 1e-6) for x, y in zip(xs, ys)]
        sw = sum(w)
        mx = sum(wi * x for wi, x in zip(w, xs)) / sw
        my = sum(wi * y for wi, y in zip(w, ys)) / sw
        sxx = sum(wi * (x - mx) ** 2 for wi, x in zip(w, xs))
        b = sum(wi * (x - mx) * (y - my) for wi, x, y in zip(w, xs, ys)) / sxx
        a = my - b * mx
    return a, b


def gain(rows, a, b):
    return mean(abs(r[a]) - abs(r[b]) for r in rows) if rows else None


def resamples(rows, reps=REPS, seed=SEED):
    """Institution-cluster resamples, as lists of rows."""
    by_school = {}
    for r in rows:
        by_school.setdefault(r['school'], []).append(r)
    keys = sorted(by_school)
    rng = random.Random(seed)
    for _ in range(reps):
        sample = []
        for _ in keys:
            sample.extend(by_school[keys[rng.randrange(len(keys))]])
        yield sample


def family(rows, groups, comparisons, reps=REPS):
    """Gains of several groups against several comparators from one set of institution resamples: percentile
    intervals, simultaneous (sup-t) intervals within each comparator's family, shares of the total gain and
    bootstrap p-values (two-sided, from the percentile of zero)."""
    est = {c: {g: gain([r for r in rows if f(r)], a, b) for g, f in groups.items()} for c, (a, b) in comparisons.items()}
    total = {c: sum(abs(r[a]) - abs(r[b]) for r in rows) for c, (a, b) in comparisons.items()}
    draws = {c: {g: [] for g in groups} for c in comparisons}
    shares = {c: {g: [] for g in groups} for c in comparisons}
    for sample in resamples(rows, reps):
        member = {g: [r for r in sample if f(r)] for g, f in groups.items()}
        for c, (a, b) in comparisons.items():
            tot = sum(abs(r[a]) - abs(r[b]) for r in sample)
            for g in groups:
                s = member[g]
                draws[c][g].append(gain(s, a, b))
                shares[c][g].append(sum(abs(r[a]) - abs(r[b]) for r in s) / tot if s and tot else None)
    out = {}
    for c in comparisons:
        sd = {g: statistics.pstdev([x for x in draws[c][g] if x is not None]) for g in groups}
        maxima = []
        for k in range(reps):
            zs = [abs(draws[c][g][k] - est[c][g]) / sd[g] for g in groups if draws[c][g][k] is not None and sd[g] > 0]
            if zs:
                maxima.append(max(zs))
        maxima.sort()
        crit = maxima[int(0.95 * len(maxima))]
        res = {'critical_value': crit, 'groups': {}}
        for g, f in groups.items():
            v = sorted(x for x in draws[c][g] if x is not None)
            sh = sorted(x for x in shares[c][g] if x is not None)
            n_inst = len({r['school'] for r in rows if f(r)})
            members = [r for r in rows if f(r)]
            res['groups'][g] = {
                'n': len(members), 'institutions': n_inst, 'gain': est[c][g],
                'relative': est[c][g] / mean(abs(r[comparisons[c][1]]) for r in members) if members else None,
                'share_of_total_gain': sum(abs(r[comparisons[c][0]]) - abs(r[comparisons[c][1]]) for r in members) / total[c],
                'share_interval': [sh[int(.025 * len(sh))], sh[int(.975 * len(sh))]],
                'percentile': [v[int(.025 * len(v))], v[int(.975 * len(v))]],
                'simultaneous': [est[c][g] - crit * sd[g], est[c][g] + crit * sd[g]],
                'p_bootstrap': min(1.0, 2 * min(sum(x >= 0 for x in v), sum(x <= 0 for x in v)) / len(v))}
        out[c] = res
    return out


def holm_bh(pvalues):
    names = sorted(pvalues, key=pvalues.get)
    m = len(names)
    holm, running = {}, 0.0
    for k, name in enumerate(names):
        running = max(running, min(1.0, (m - k) * pvalues[name]))
        holm[name] = running
    bh, running = {}, 1.0
    for k in range(m - 1, -1, -1):
        name = names[k]
        running = min(running, pvalues[name] * m / (k + 1))
        bh[name] = running
    return {name: {'p': pvalues[name], 'holm': holm[name], 'bh': bh[name]} for name in names}


def main():
    rows = load_rows()
    j2 = common_rows(rows, ('v3', 'baseline'))
    assert len(j2) == 1521
    history = load_history()
    with (PAPER / 'data/history-2024.csv').open(newline='') as f:
        changed_2425 = {int(r['gid']): r['rules_changed_2024_2025'] == 'True' for r in csv.DictReader(f)}
    inputs = {d['gid']: d for d in json.loads((PAPER / 'data/baseline-inputs.json').read_text())['departments']}
    prior24 = {d['gid']: d['prior2024'] for d in json.loads((PAPER / 'data/history-inputs.json').read_text())['departments']}
    with input_path('engine-2026.csv').open(newline='') as f:
        engine = {int(r['gid']): r for r in csv.DictReader(f)}
    num = lambda x: float(x) if x not in ('', None) else None

    # Ex ante slope of the baseline's 2025 departure on the 2024->2025 quota change (all departments with both years).
    train = []
    for g, h in history.items():
        if h['b25'] is not None and h['cutoff_2025'] and h['weight_total_2025'] and h['quota_2024'] and h['quota_2025']:
            train.append({'gid': g, 'x': math.log(h['quota_2025'] / h['quota_2024']),
                          'y': (h['cutoff_2025'] - h['b25']) / h['weight_total_2025'], 'changed': changed_2425.get(g)})
    a_ols, beta = ols([t['x'] for t in train], [t['y'] for t in train])
    _, beta_lad = lad([t['x'] for t in train], [t['y'] for t in train])
    kept = [t for t in train if t['changed'] is False]
    _, beta_unchanged = ols([t['x'] for t in kept], [t['y'] for t in kept])

    for r in j2:
        errors(r)
        r['region'] = region_of(r)
        q25 = history[r['gid']]['quota_2025']
        r['dq_signed'] = math.log(r['official_quota'] / q25) if q25 and r['official_quota'] > 0 else None
        r['dq'] = abs(r['dq_signed']) if r['dq_signed'] is not None else None
        r['rule'] = rule_change(inputs[r['gid']]) if r['gid'] in inputs else None
        r['Q'] = beta * r['dq_signed'] if r['dq_signed'] is not None else 0.0     # quota-implied departure, grades
        r['eQ'] = r['eH'] + r['Q']                                                  # quota-adjusted history
        r['eR'] = LAMBDA * r['eV'] + (1 - LAMBDA) * r['eQ']                         # combination re-anchored on it
        e = engine[r['gid']]
        r['eE'] = (num(e['engine_final']) - r['actual']) / r['weightTotal']        # engine, with its quota adjustment
        r['eA'] = (num(e['august_rule_engine']) - r['actual']) / r['weightTotal']  # August rule (percentile scale) with it
        r['eSE'] = LAMBDA * r['eV'] + (1 - LAMBDA) * r['eE']                        # score-scale combination with it
        r['eF'] = (r['fractional'] - r['actual']) / r['weightTotal'] if r['fractional'] is not None else None

    n = len(j2)
    out = {'note': 'exploratory; added after the seventh round of simulated reviews; department-level files only',
           'n_J2': n}

    # Quota-adjusted history.
    def mae(rows_, key):
        return mean(abs(r[key]) for r in rows_)
    comp = {'combination_vs_baseline': ('eM', 'eH'), 'combination_vs_quota_adjusted': ('eM', 'eQ'),
            'reanchored_vs_quota_adjusted': ('eR', 'eQ'), 'quota_adjusted_vs_baseline': ('eQ', 'eH'),
            'combination_vs_engine': ('eM', 'eE'), 'august_rule_vs_engine': ('eA', 'eE'),
            'score_scale_with_engine_vs_engine': ('eSE', 'eE'), 'engine_vs_baseline': ('eE', 'eH'),
            'engine_vs_quota_adjusted': ('eE', 'eQ')}
    overall = family(j2, {'all': lambda r: True}, comp)
    out['quota_adjusted'] = {
        'training_departments': len(train), 'slope_ols': beta, 'intercept_ols_not_used': a_ols, 'slope_lad': beta_lad,
        'slope_ols_rules_unchanged_2024_2025': beta_unchanged, 'training_rules_unchanged': len(kept),
        'departments_with_quota_change': sum(r['dq_signed'] is not None for r in j2),
        'mae': {k: mae(j2, k) for k in ('eH', 'eQ', 'eM', 'eR', 'eV', 'eE', 'eA', 'eSE')},
        'bias': {k: mean(r[k] for r in j2) for k in ('eH', 'eQ', 'eM', 'eR', 'eE', 'eA')},
        'at_least_four_grades': {k: mean(abs(r[k]) >= 4 for r in j2) for k in ('eH', 'eQ', 'eM', 'eR', 'eE')},
        'comparisons': {c: overall[c]['groups']['all'] for c in comp},
        'mae_optimal_weight_against_quota_adjusted': min(((l / 200, mean(abs(l / 200 * r['eV'] + (1 - l / 200) * r['eQ']) for r in j2))
                                                         for l in range(201)), key=lambda x: x[1]),
        'mae_optimal_weight_against_engine': min(((l / 200, mean(abs(l / 200 * r['eV'] + (1 - l / 200) * r['eE']) for r in j2))
                                                  for l in range(201)), key=lambda x: x[1]),
        'error_correlation': {'v3_baseline': statistics.correlation([r['eV'] for r in j2], [r['eH'] for r in j2]),
                              'v3_quota_adjusted': statistics.correlation([r['eV'] for r in j2], [r['eQ'] for r in j2]),
                              'v3_engine': statistics.correlation([r['eV'] for r in j2], [r['eE'] for r in j2])}}

    # Table 5 groups (each department in exactly one group; the department without a 2025 quota is among the 179
    # whose subjects changed) and Table 6 rows, against three comparators.
    t5 = {'subjects changed': lambda r: r['rule'] == 'subjects',
          'multipliers changed alone': lambda r: r['rule'] == 'multipliers',
          'rules unchanged, quota change above 0.35': lambda r: r['rule'] == 'unchanged' and r['dq'] is not None and r['dq'] > 0.35,
          'rules unchanged, quota change 0.05-0.35': lambda r: r['rule'] == 'unchanged' and r['dq'] is not None and 0.05 < r['dq'] <= 0.35,
          'rules unchanged, quota change above 0 and at most 0.05': lambda r: r['rule'] == 'unchanged' and r['dq'] is not None and 0 < r['dq'] <= 0.05,
          'rules and quota unchanged': lambda r: r['rule'] == 'unchanged' and r['dq'] == 0}
    assert sum(sum(1 for r in j2 if f(r)) for f in t5.values()) == n
    three = {'baseline': ('eM', 'eH'), 'engine': ('eM', 'eE'), 'quota_adjusted': ('eM', 'eQ'),
             'engine_august_rule': ('eA', 'eE'), 'quota_adjusted_reanchored': ('eR', 'eQ')}
    out['table5'] = family(j2, t5, three)
    bands = ((0, 30), (30, 40), (40, 45), (45, 50), (50, 61))
    t6 = {**{f'level {lo}-{hi if hi < 61 else 60}': (lambda r, lo=lo, hi=hi: lo <= r['level'] < hi) for lo, hi in bands},
          **{f'level 0-30, {g}': (lambda r, g=g: r['level'] < 30 and r['region'] == g) for g in ('north', 'central', 'south', 'east_and_kinmen')}}
    out['table6'] = family(j2, t6, three)
    out['table6_extra'] = {name: {'n': len(s), 'gain_vs_baseline': gain(s, 'eM', 'eH'), 'gain_vs_engine': gain(s, 'eM', 'eE'),
                                  'gain_vs_quota_adjusted': gain(s, 'eM', 'eQ')}
                           for name, s in (('level 0-30, south, private', [r for r in j2 if r['level'] < 30 and r['region'] == 'south' and not public(r)]),)}

    # Direction agreement of the quota-implied departure Q, and of S on Q's flags.
    def agree(rows_, key):
        flagged = [r for r in rows_ if abs(r[key]) >= 1 and r['D'] != 0]
        return {'flagged': len(flagged), 'agreement': mean((r[key] > 0) == (r['D'] > 0) for r in flagged) if flagged else None}
    q_flags = [r for r in j2 if abs(r['Q']) >= 1 and r['D'] != 0]
    out['q_reference'] = {'Q': agree(j2, 'Q'), 'S': agree(j2, 'S'),
                          'S_on_Q_flags': {'n': len(q_flags), 'agreement': mean((r['S'] > 0) == (r['D'] > 0) for r in q_flags)},
                          'S_on_Q_flags_with_abs_S_at_least_1': agree(q_flags, 'S'),
                          'rules_unchanged_small_Q': agree([r for r in j2 if r['rule'] == 'unchanged' and abs(r['Q']) < 0.25], 'S'),
                          'correlation_S_Q': statistics.correlation([r['S'] for r in j2], [r['Q'] for r in j2])}

    # S and the older history (R) on the same departments.
    j2h = [r for r in j2 if history[r['gid']]['h24'] is not None]
    for r in j2h:
        r['h24'] = history[r['gid']]['h24']
        r['R'] = (r['h24'] - r['baseline']) / r['weightTotal']
    def pair(s):
        a, b = agree(s, 'S'), agree(s, 'R')
        return (a['agreement'] - b['agreement']) if a['agreement'] is not None and b['agreement'] is not None else None
    draws = sorted(v for v in (pair(s) for s in resamples(j2h)) if v is not None)
    out['older_history'] = {'n': len(j2h), 'institutions': len({r['school'] for r in j2h}), 'S': agree(j2h, 'S'),
                            'older_history': agree(j2h, 'R'), 'difference': pair(j2h),
                            'interval': [draws[int(.025 * len(draws))], draws[int(.975 * len(draws))]]}

    # Fractional in place of v3.
    jf = [r for r in j2 if r['eF'] is not None]
    for r in jf:
        r['SF'] = r['eF'] - r['eH']
        r['eMF'] = LAMBDA * r['eF'] + (1 - LAMBDA) * r['eH']
    centre = mean(r['SF'] for r in jf)
    for r in jf:
        r['eMFc'] = r['eH'] + LAMBDA * (r['SF'] - centre)
    ff = family(jf, {'all': lambda r: True}, {'fractional': ('eMF', 'eH'), 'fractional_centered': ('eMFc', 'eH')})
    out['fractional'] = {'n': len(jf), 'mae': {'baseline': mae(jf, 'eH'), 'fractional': mae(jf, 'eF'), 'combination': mae(jf, 'eMF'),
                                               'centered_combination': mae(jf, 'eMFc')},
                         'mean_departure': centre, 'agreement': agree(jf, 'SF'),
                         'gain': ff['fractional']['groups']['all'], 'gain_centered': ff['fractional_centered']['groups']['all'],
                         'share_of_v3_gain_from_interpolation': 1 - ff['fractional']['groups']['all']['gain'] / overall['combination_vs_baseline']['groups']['all']['gain']}

    # Transport: the groups' 2026 gains reweighted to the 2024->2025 composition.
    def group_2025(g):
        p = inputs.get(g, {}).get('prior')
        p24 = prior24.get(g)
        h = history.get(g)
        if not p or not p24 or not p.get('items') or not p24.get('items') or not h or not h['quota_2024'] or not h['quota_2025']:
            return None
        kind = rule_change({'items': p['items'], 'prior': p24})
        d = abs(math.log(h['quota_2025'] / h['quota_2024']))
        if kind in ('subjects', 'multipliers'):
            return 'rules changed'
        if d == 0:
            return 'rules and quota unchanged'
        if d <= 0.05:
            return 'quota change at most 0.05'
        if d <= 0.35:
            return 'quota change 0.05-0.35'
        return 'quota change above 0.35'
    def group_2026(r):
        if r['rule'] in ('subjects', 'multipliers'):
            return 'rules changed'
        if r['dq'] == 0:
            return 'rules and quota unchanged'
        if r['dq'] <= 0.05:
            return 'quota change at most 0.05'
        if r['dq'] <= 0.35:
            return 'quota change 0.05-0.35'
        return 'quota change above 0.35'
    for r in j2:
        r['g26'] = group_2026(r)
    comp25 = {}
    for g in history:
        k = group_2025(g)
        if k:
            comp25[k] = comp25.get(k, 0) + 1
    tot25 = sum(comp25.values())
    w25 = {k: v / tot25 for k, v in comp25.items()}
    w26 = {k: sum(r['g26'] == k for r in j2) / n for k in w25}
    def reweighted(by_group, weights, a='eM', b='eH', keep=None):
        keys = [k for k in weights if keep is None or k in keep]
        tw = sum(weights[k] for k in keys)
        g_, m_ = 0.0, 0.0
        for k in keys:
            s = by_group.get(k)
            if not s:
                return None
            g_ += weights[k] / tw * gain(s, a, b)
            m_ += weights[k] / tw * mean(abs(r[b]) for r in s)
        return g_, g_ / m_
    def split(rows_):
        by = {}
        for r in rows_:
            by.setdefault(r['g26'], []).append(r)
        return by
    tr = {'composition_2025': {k: {'departments': comp25[k], 'share': w25[k], 'share_2026_J2': w26[k]} for k in w25}}
    specs = [(label, keep, cname, ab) for label, keep in (('all', None), ('rules unchanged', [k for k in w25 if k != 'rules changed']),
                                                         ('rules and quota unchanged', ['rules and quota unchanged']))
             for cname, ab in (('baseline', ('eM', 'eH')), ('quota_adjusted', ('eM', 'eQ')), ('engine', ('eM', 'eE')))]
    draws_t = {k: [] for k in range(len(specs))}
    for s in resamples(j2):
        by = split(s)
        for k, (_, keep, _, (a, b)) in enumerate(specs):
            v = reweighted(by, w25, a, b, keep)
            if v is not None:
                draws_t[k].append(v[0])
    by_all = split(j2)
    for k, (label, keep, cname, (a, b)) in enumerate(specs):
        point = reweighted(by_all, w25, a, b, keep)
        same = reweighted(by_all, w26, a, b, keep)
        vals = sorted(draws_t[k])
        tr[f'{label} vs {cname}'] = {'gain_2025_composition': point[0], 'relative_2025_composition': point[1],
                                     'gain_2026_composition': same[0], 'relative_2026_composition': same[1],
                                     'interval': [vals[int(.025 * len(vals))], vals[int(.975 * len(vals))]]}
    out['transport'] = tr

    # A shift common to the year, by group (errors move by c grades).
    sh = {}
    for c in (-1.17, -0.58, 0.58, 1.17):
        row = {}
        for name, f in t5.items():
            s = [r for r in j2 if f(r)]
            row[name] = {k: mean(abs(r[a] + c) - abs(r[b] + c) for r in s) / mean(abs(r[b] + c) for r in s)
                         for k, (a, b) in (('relative_vs_baseline', ('eM', 'eH')), ('relative_vs_quota_adjusted', ('eM', 'eQ')))}
            row[name]['gain_vs_baseline'] = mean(abs(r['eM'] + c) - abs(r['eH'] + c) for r in s)
        row['all'] = {'gain_vs_baseline': mean(abs(r['eM'] + c) - abs(r['eH'] + c) for r in j2),
                      'relative_vs_baseline': mean(abs(r['eM'] + c) - abs(r['eH'] + c) for r in j2) / mean(abs(r['eH'] + c) for r in j2),
                      'relative_vs_quota_adjusted': mean(abs(r['eM'] + c) - abs(r['eQ'] + c) for r in j2) / mean(abs(r['eQ'] + c) for r in j2),
                      'relative_reanchored_vs_quota_adjusted': mean(abs(r['eR'] + c) - abs(r['eQ'] + c) for r in j2) / mean(abs(r['eQ'] + c) for r in j2),
                      'relative_vs_engine': mean(abs(r['eM'] + c) - abs(r['eE'] + c) for r in j2) / mean(abs(r['eE'] + c) for r in j2)}
        sh[f'{c:+.2f}'] = row
    unchanged = [r for r in j2 if t5['rules and quota unchanged'](r)]
    mh, mv = mean(r['eH'] for r in unchanged), mean(r['eV'] for r in unchanged)
    sh['rules_and_quota_unchanged_levels'] = {
        'bias_baseline': mh, 'bias_v3': mv,
        'gain_after_removing_group_mean_errors': mean(abs(LAMBDA * (r['eV'] - mv) + (1 - LAMBDA) * (r['eH'] - mh)) - abs(r['eH'] - mh) for r in unchanged)}
    out['shift_by_group'] = sh

    # Decision time with only the runs completed before each day began (as of the start of the day).
    runs = {x['label'][4:]: x['j2']['mixMinusBaseline'] for x in json.loads((PAPER / 'data/author-checks.json').read_text())['sections']['runs']['summary']
            if x['label'].startswith('run-ast_') and 'no-zero' not in x['label']}
    base_mae = mae(j2, 'eH')
    def as_of(day, strict):
        before = [run for run, when in RUNS if when < f'{day} 00:00' or (not strict and when.startswith(day) and when < f'{day} 02:00')]
        return runs[before[-1]] if before else 0.0
    dt = {}
    for label, strict in (('strict', True), ('first_run_of_8_august_6_counted', False)):
        g = sum(share * as_of(day, strict) for day, share in DAY_SHARE)
        dt[label] = {'gain': g, 'relative': g / base_mae, 'share_of_evaluated_gain': g / runs[EVALUATED],
                     'runs_used': {day: next((run for run, when in reversed(RUNS) if when < f'{day} 00:00' or (not strict and when.startswith(day) and when < f'{day} 02:00')), None)
                                   for day, _ in DAY_SHARE}}
    out['decision_time_as_of'] = dt

    # Multiplicity across the subgroup gains of Tables 5 and 6 (against the baseline).
    pv = {f'T5 {g}': v['p_bootstrap'] for g, v in out['table5']['baseline']['groups'].items()}
    pv.update({f'T6 {g}': v['p_bootstrap'] for g, v in out['table6']['baseline']['groups'].items()})
    out['multiplicity'] = holm_bh(pv)
    pvq = {f'T5 {g}': v['p_bootstrap'] for g, v in out['table5']['quota_adjusted']['groups'].items()}
    pvq.update({f'T6 {g}': v['p_bootstrap'] for g, v in out['table6']['quota_adjusted']['groups'].items()})
    out['multiplicity_quota_adjusted'] = holm_bh(pvq)

    path = output_path('seventh-review.json')
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(path)


if __name__ == '__main__':
    main()
