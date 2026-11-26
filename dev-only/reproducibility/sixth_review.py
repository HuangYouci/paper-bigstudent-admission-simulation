"""Department-level checks added after the sixth round of simulated reviews (exploratory; plan v0.25, section H).

Every number comes from the released files (department-benchmark.csv, history-2024.csv, baseline-inputs.json,
official-rules-audit.csv, and the stored aggregates author-checks.json and bootstrap-summary.json). Intervals resample
institutions 4,000 times with the seed of the main text.

  common_shock      the combination's gain if every error moved by the same amount (a shift common to the year);
  decision_time     the gain of the saved runs weighted by the share of registrants who completed registration each day;
  quota_weighted    quota-weighted errors and coverage, by department count and by places, for the groups of Table 5;
  cutpoints         the low-level gain in the south and in the east and Kinmen at other level cutpoints, and by level bin;
  caution           the change in needless caution (official cutoff a grade below the prediction) below and above level 30;
  encompassing      Harvey-Leybourne-Newbold statistics in both directions and the through-origin slope of plan v0.15;
  placement_ci      Wilson intervals for the placement shares of Table S20b;
  margins           ex ante 90% margins by level from the baseline's 2025 backtest, and 2026 exceedance;
  plan_v018         the department-level bootstrap coverage that plan v0.18 specified (from bootstrap-summary.json);
  dose_response     the gain by the size of the quota change and by rule change, and the intercept of a regression;
  practical         departments where the combination is worse, contributions to the gain, weighted-total units,
                    listing-weighted error;
  display_rules     falling back to history at thin low-level departments or where the simulation leaves a department
                    underfilled;
  release           headline results on stricter release sets;
  filled            main measures for officially filled and underfilled departments;
  heterogeneity     REML between-institution variance and the correlation of institution gains with their standard errors;
  pooling           partially pooled (normal-normal, REML) subgroup gains;
  no_history        a synthetic fallback for departments without a previous cutoff;
  year_shift        the expected gain when the simulation's level relative to history varies across years.
Writes sixth-review.json.
"""
import csv
import json
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, load_rows, common_rows, output_path  # noqa: E402
from history_checks import REPS, load_history  # noqa: E402
from revision_checks import (LAMBDA, LEVEL_BANDS, SEED, _t_quantile, ci, errors, gain, mae, mean, public,  # noqa: E402
                             region_of)
from robustness_checks import rule_change  # noqa: E402

COMPLETED = {'2026-08-05': 0.1056, '2026-08-06': 0.1420, '2026-08-07': 0.3380, '2026-08-08': 0.4144}  # UAC (2026a)
RUN_TIME_TW = {'ast_20260805T175904Z': ('2026-08-06', '01:59'), 'ast_20260806T120005Z': ('2026-08-06', '20:00'),
               'ast_20260807T022008Z': ('2026-08-07', '10:20'), 'ast_20260807T120012Z': ('2026-08-07', '20:00'),
               'ast_20260808T035958Z': ('2026-08-08', '11:59')}


def cluster_draws(rows, stat, reps=REPS, seed=SEED):
    groups = {}
    for r in rows:
        groups.setdefault(r['school'], []).append(r)
    keys = list(groups)
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        sample = []
        for _ in keys:
            sample.extend(groups[keys[rng.randrange(len(keys))]])
        v = stat(sample)
        if v is not None:
            vals.append(v)
    return vals


def cluster_t(rows, value):
    """Mean of value(r) and its institution-clustered t statistic (CR1)."""
    groups = {}
    for r in rows:
        groups.setdefault(r['school'], []).append(value(r))
    n = sum(len(v) for v in groups.values())
    m = sum(sum(v) for v in groups.values()) / n
    G = len(groups)
    var = G / (G - 1) * sum((sum(x - m for x in v)) ** 2 for v in groups.values()) / n ** 2
    return {'mean': m, 't': m / math.sqrt(var), 'institutions': G}


def wilson(k, n, z=1.959963984540054):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [c - h, c + h]


def newcombe(k1, n1, k2, n2):
    l1, u1 = wilson(k1, n1)
    l2, u2 = wilson(k2, n2)
    p1, p2 = k1 / n1, k2 / n2
    return [p1 - p2 - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), p1 - p2 + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)]


def reml(y, s2):
    """REML estimate of tau^2 for y_k ~ N(mu, s2_k + tau^2), by grid search; returns tau, mu, se(mu)."""
    best = None
    for i in range(0, 4001):
        t2 = (i / 2000) ** 2
        w = [1 / (v + t2) for v in s2]
        mu = sum(wi * yi for wi, yi in zip(w, y)) / sum(w)
        ll = -0.5 * sum(math.log(v + t2) for v in s2) - 0.5 * math.log(sum(w)) - 0.5 * sum(wi * (yi - mu) ** 2 for wi, yi in zip(w, y))
        if best is None or ll > best[0]:
            best = (ll, t2, mu, math.sqrt(1 / sum(w)))
    return {'tau': math.sqrt(best[1]), 'mu': best[2], 'se_mu': best[3]}


def main():
    rows = load_rows()
    j2 = common_rows(rows, ('v3', 'baseline'))
    for r in j2:
        errors(r)
        r['region'] = region_of(r)
    assert len(j2) == 1521
    history = load_history()
    inputs = {d['gid']: d for d in json.loads((PAPER / 'data/baseline-inputs.json').read_text())['departments']}
    audit = {int(r['gid']): int(r['admitted_including_extra']) for r in csv.DictReader((PAPER / 'data/official-rules-audit.csv').open())}
    for r in j2:
        h = history[r['gid']]
        r['rule'] = rule_change(inputs[r['gid']]) if r['gid'] in inputs else None
        q25 = h['quota_2025']
        r['dq'] = abs(math.log(r['official_quota'] / q25)) if q25 and r['official_quota'] > 0 else None
        r['official_under'] = audit[r['gid']] < r['official_quota']
    total_gain = gain(j2)
    out = {'note': 'exploratory; plan v0.25 (section H), written after the sixth round of simulated reviews', 'n_J2': len(j2)}

    # H1. A shift common to the year.
    shock = {}
    for c in (-1.17, -0.7, -0.35, 0.0, 0.35, 0.7, 1.17):
        g = mean(abs(r['eM'] + c) - abs(r['eH'] + c) for r in j2)
        shock[f'{c:+.2f}'] = {'gain': g, 'relative': g / mean(abs(r['eH'] + c) for r in j2)}
    out['common_shock'] = shock

    # H2. Decision-time weighting of the saved runs' gains.
    runs = {x['label'][4:]: x['j2']['mixMinusBaseline'] for x in json.loads((PAPER / 'data/author-checks.json').read_text())['sections']['runs']['summary']
            if x['label'].startswith('run-ast_') and 'no-zero' not in x['label']}
    last_of_day, first_of_day = {}, {}
    for run, (day, _) in sorted(RUN_TIME_TW.items(), key=lambda kv: kv[1]):
        last_of_day[day] = run
        first_of_day.setdefault(day, run)
    weighted = lambda pick: sum(share * (runs[pick[day]] if day in pick else 0.0) for day, share in COMPLETED.items())
    evaluated = runs['ast_20260815T150000Z']
    base_mae = mae(j2, 'eH')
    out['decision_time'] = {'run_gains': runs, 'completed_share_by_day': COMPLETED,
                            'last_run_of_day': {'gain': weighted(last_of_day), 'relative': weighted(last_of_day) / base_mae,
                                                'share_of_evaluated_gain': weighted(last_of_day) / evaluated},
                            'first_run_of_day': {'gain': weighted(first_of_day), 'relative': weighted(first_of_day) / base_mae,
                                                 'share_of_evaluated_gain': weighted(first_of_day) / evaluated}}

    # H3. Quota-weighted errors and coverage by group.
    with_base = [r for r in rows if r['baseline'] is not None and r['actual'] and r['actual'] > 0]
    for r in with_base:
        r['level'] = r['baseline'] / r['weightTotal']
        r['region'] = region_of(r)
    in_j2 = {r['gid'] for r in j2}
    groups = {'all': lambda r: True, **{f'level {lo}-{hi}': (lambda r, lo=lo, hi=hi: lo <= r['level'] < hi) for lo, hi in LEVEL_BANDS},
              **{f'below 30, {g}': (lambda r, g=g: r['level'] < 30 and r['region'] == g) for g in ('north', 'central', 'south', 'east_and_kinmen')},
              'below 30, south, private': lambda r: r['level'] < 30 and r['region'] == 'south' and not public(r),
              'public': public, 'private': lambda r: not public(r)}
    qw = {}
    for name, f in groups.items():
        s = [r for r in j2 if f(r)]
        base_set = [r for r in with_base if f(r)]
        q = [r['official_quota'] for r in s]
        wmae = lambda key: sum(abs(r[key]) * r['official_quota'] for r in s) / sum(q)
        qw[name] = {'n': len(s), 'mae_baseline': mae(s, 'eH'), 'mae_combination': mae(s, 'eM'), 'relative': mae(s, 'eM') / mae(s, 'eH') - 1,
                    'quota_weighted_mae_baseline': wmae('eH'), 'quota_weighted_mae_combination': wmae('eM'),
                    'quota_weighted_relative': wmae('eM') / wmae('eH') - 1,
                    'coverage_departments': len(s) / len(base_set) if base_set else None,
                    'coverage_places': sum(q) / sum(r['official_quota'] for r in base_set) if base_set else None,
                    'departments_with_baseline': len(base_set)}
    out['quota_weighted'] = qw

    # H4. Cutpoints for the low-level regional results, and the gain by level bin.
    cut = {}
    for reg in ('south', 'east_and_kinmen'):
        for c in (25, 27.5, 30, 32.5, 35):
            s = [r for r in j2 if r['region'] == reg and r['level'] < c]
            cut[f'{reg} below {c}'] = {'n': len(s), 'institutions': len({r['school'] for r in s}), 'gain': gain(s),
                                       'relative': mae(s, 'eM') / mae(s, 'eH') - 1}
    s = [r for r in j2 if r['region'] == 'south' and r['level'] < 30]
    by_school = {}
    for r in s:
        by_school.setdefault(r['school'], []).append(r)
    cut['south below 30 by institution'] = sorted(({'departments': len(v), 'private': not public(v[0]), 'gain': gain(v)}
                                                   for v in by_school.values()), key=lambda x: -x['departments'])
    bins = []
    for lo in range(15, 60, 5):
        b = [r for r in j2 if lo <= r['level'] < lo + 5]
        if len(b) >= 20:
            bins.append({'level': [lo, lo + 5], 'n': len(b), 'gain': gain(b), 'relative': mae(b, 'eM') / mae(b, 'eH') - 1,
                         'interval': ci(b, gain) if len({r['school'] for r in b}) >= 5 else None})
    cut['by_level_bin'] = bins
    out['cutpoints'] = cut

    # H5. Needless caution below and above level 30.
    caution = lambda s: mean(r['eM'] >= 1 for r in s) - mean(r['eH'] >= 1 for r in s)
    low = lambda s: [r for r in s if r['level'] < 30]
    high = lambda s: [r for r in s if r['level'] >= 30]
    contrast = lambda s: (caution(low(s)) - caution(high(s))) if low(s) and high(s) else None
    out['caution'] = {'below_30': {'baseline': mean(r['eH'] >= 1 for r in low(j2)), 'combination': mean(r['eM'] >= 1 for r in low(j2))},
                      'at_least_30': {'baseline': mean(r['eH'] >= 1 for r in high(j2)), 'combination': mean(r['eM'] >= 1 for r in high(j2))},
                      'difference_in_change': contrast(j2), 'interval': ci(j2, contrast)}

    # H6. Encompassing in both directions (HLN) and the slope through the origin.
    hln_h = cluster_t(j2, lambda r: (r['eH'] - r['eV']) * r['eH'])  # > 0: v3 adds information to the baseline
    hln_v = cluster_t(j2, lambda r: (r['eV'] - r['eH']) * r['eV'])  # > 0: the baseline adds information to v3
    sxx = sum(r['S'] ** 2 for r in j2)
    b0 = sum(r['S'] * r['D'] for r in j2) / sxx
    groups_ = {}
    for r in j2:
        groups_.setdefault(r['school'], []).append(r)
    G = len(groups_)
    var0 = G / (G - 1) * sum(sum(r['S'] * (r['D'] - b0 * r['S']) for r in v) ** 2 for v in groups_.values()) / sxx ** 2
    out['encompassing'] = {'hln_baseline_encompasses_v3': hln_h, 'hln_v3_encompasses_baseline': hln_v,
                           'slope_through_origin': b0, 't_through_origin': b0 / math.sqrt(var0)}

    # H7. Wilson intervals for Table S20b.
    placements = json.loads((PAPER / 'data/author-checks.json').read_text())['sections']['placements']['report']
    pci = {}
    for label, rep in placements.items():
        for rule in ('divisible', 'wholePerson'):
            lo, hi = rep[rule]['1'], rep[rule]['5']
            pci[f'{label} {rule}'] = {
                'more_favorable_lowest': [lo['simulationEarlier'] / lo['records'], wilson(lo['simulationEarlier'], lo['records'])],
                'more_favorable_highest': [hi['simulationEarlier'] / hi['records'], wilson(hi['simulationEarlier'], hi['records'])],
                'more_favorable_difference': newcombe(lo['simulationEarlier'], lo['records'], hi['simulationEarlier'], hi['records']),
                'only_simulation_lowest': [lo['simulationOnly'] / lo['records'], wilson(lo['simulationOnly'], lo['records'])],
                'only_simulation_highest': [hi['simulationOnly'] / hi['records'], wilson(hi['simulationOnly'], hi['records'])],
                'only_simulation_difference': newcombe(lo['simulationOnly'], lo['records'], hi['simulationOnly'], hi['records'])}
    out['placement_ci'] = pci

    # H8. Ex ante 90% margins by level from the baseline's 2025 backtest.
    back = []
    for g, h in history.items():
        if h['b25'] is not None and h['cutoff_2025'] and h['weight_total_2025']:
            back.append({'gid': g, 'level': h['b25'] / h['weight_total_2025'],
                         'shortfall': (h['cutoff_2025'] - h['b25']) / h['weight_total_2025']})
    q90 = lambda v: sorted(v)[int(0.9 * (len(v) - 1))]
    overall = q90([b['shortfall'] for b in back])
    band_margin = {}
    for lo, hi in LEVEL_BANDS:
        v = [b['shortfall'] for b in back if lo <= b['level'] < hi]
        band_margin[f'{lo}-{hi}'] = {'n': len(v), 'margin': q90(v)}
    def exceed(s, key, margin_of):
        return mean(-r[key] > margin_of(r) for r in s)
    band_of = lambda r: next(f'{lo}-{hi}' for lo, hi in LEVEL_BANDS if lo <= r['level'] < hi)
    out['margins'] = {'backtest_departments': len(back), 'overall_margin': overall, 'by_level': band_margin,
                      'exceeded_overall_margin': {'baseline': exceed(j2, 'eH', lambda r: overall), 'combination': exceed(j2, 'eM', lambda r: overall)},
                      'exceeded_level_margin': {'baseline': exceed(j2, 'eH', lambda r: band_margin[band_of(r)]['margin']),
                                                'combination': exceed(j2, 'eM', lambda r: band_margin[band_of(r)]['margin'])},
                      'by_level_exceeded': {k: {'baseline': exceed([r for r in j2 if band_of(r) == k], 'eH', lambda r, k=k: band_margin[k]['margin']),
                                                'combination': exceed([r for r in j2 if band_of(r) == k], 'eM', lambda r, k=k: band_margin[k]['margin'])}
                                            for k in band_margin},
                      'backtest_2025_official_above_prediction': mean(b['shortfall'] > 0 for b in back),
                      'backtest_2025_official_above_by_a_grade': mean(b['shortfall'] >= 1 for b in back),
                      'if_2026_errors_shifted_like_2025': {
                          'baseline': mean(-(r['eH'] - 1.17) > band_margin[band_of(r)]['margin'] for r in j2),
                          'combination': mean(-(r['eM'] - 1.17) > band_margin[band_of(r)]['margin'] for r in j2)}}

    # H9. Plan v0.18 (H6): the department-level bootstrap.
    boot = json.loads((PAPER / 'data/bootstrap-summary.json').read_text())
    out['plan_v018'] = {'departments': boot['departmentsTested'], 'official_inside_90': boot['officialInside90'],
                        'median_width_90_grades': boot['medianStandardizedWidth90'], 'replicates': boot['B'],
                        'replicate_v3_mae_median': boot['v3MAE']['p50']}

    # H10. Dose response in the size of the quota change.
    bins = (('subjects changed', lambda r: r['rule'] == 'subjects'), ('multipliers changed', lambda r: r['rule'] == 'multipliers'),
            ('rules unchanged, quota unchanged', lambda r: r['rule'] == 'unchanged' and r['dq'] == 0),
            ('rules unchanged, |dlog q| <= 0.05', lambda r: r['rule'] == 'unchanged' and r['dq'] is not None and 0 < r['dq'] <= 0.05),
            ('rules unchanged, 0.05-0.15', lambda r: r['rule'] == 'unchanged' and r['dq'] is not None and 0.05 < r['dq'] <= 0.15),
            ('rules unchanged, 0.15-0.35', lambda r: r['rule'] == 'unchanged' and r['dq'] is not None and 0.15 < r['dq'] <= 0.35),
            ('rules unchanged, > 0.35', lambda r: r['rule'] == 'unchanged' and r['dq'] is not None and r['dq'] > 0.35),
            ('rules unchanged, 0.05-0.35 (the two middle bins together)', lambda r: r['rule'] == 'unchanged' and r['dq'] is not None and 0.05 < r['dq'] <= 0.35),
            ('no 2025 quota or rule record', lambda r: r['rule'] is None or r['dq'] is None))
    dose = {}
    for name, f in bins:
        s = [r for r in j2 if f(r)]
        flagged = [r for r in s if abs(r['S']) >= 1 and r['D'] != 0]
        dose[name] = {'n': len(s), 'gain': gain(s) if s else None, 'share_of_total_gain': sum(abs(r['eM']) - abs(r['eH']) for r in s) / (total_gain * len(j2)),
                      'interval': ci(s, gain) if len({r['school'] for r in s}) >= 5 else None,
                      'agreement': mean((r['S'] > 0) == (r['D'] > 0) for r in flagged) if flagged else None, 'flagged': len(flagged)}
    reg = [r for r in j2 if r['rule'] is not None and r['dq'] is not None]
    def intercept(sample):
        X = [[1.0, r['dq'], float(r['rule'] == 'subjects'), float(r['rule'] == 'multipliers')] for r in sample]
        y = [abs(r['eM']) - abs(r['eH']) for r in sample]
        k = 4
        xtx = [[sum(a[i] * a[j] for a in X) for j in range(k)] for i in range(k)]
        xty = [sum(a[i] * b for a, b in zip(X, y)) for i in range(k)]
        m = [row[:] + [v] for row, v in zip(xtx, xty)]
        for i in range(k):
            p = max(range(i, k), key=lambda t: abs(m[t][i]))
            m[i], m[p] = m[p], m[i]
            if abs(m[i][i]) < 1e-12:
                return None
            for t in range(k):
                if t != i:
                    f = m[t][i] / m[i][i]
                    m[t] = [a - f * b for a, b in zip(m[t], m[i])]
        return [m[i][k] / m[i][i] for i in range(k)]
    coef = intercept(reg)
    out['dose_response'] = {'groups': dose, 'regression': {'n': len(reg), 'intercept': coef[0], 'per_unit_dlog_q': coef[1],
                                                           'subjects_changed': coef[2], 'multipliers_changed': coef[3],
                                                           'intercept_interval': ci(reg, lambda s: (intercept(s) or [None])[0])}}

    # H11. Practical meaning.
    diffs = [abs(r['eM']) - abs(r['eH']) for r in j2]
    contrib = {}
    for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 10 ** 9)):
        s = [r for r in j2 if lo <= abs(r['eH']) < hi]
        contrib[f'{lo}-{hi if hi < 10 ** 9 else "inf"}'] = {'n': len(s), 'share_of_total_gain': sum(abs(r['eM']) - abs(r['eH']) for r in s) / sum(diffs)}
    L = [r['applicant_count'] for r in j2]
    lw = lambda key: sum(abs(r[key]) * r['applicant_count'] for r in j2) / sum(L)
    out['practical'] = {'worse_than_baseline': mean(d > 0 for d in diffs), 'worse_by_half_grade': mean(d >= 0.5 for d in diffs),
                        'better_by_half_grade': mean(d <= -0.5 for d in diffs),
                        'off_by_a_grade_or_more': {'baseline': mean(abs(r['eH']) >= 1 for r in j2), 'combination': mean(abs(r['eM']) >= 1 for r in j2)},
                        'contribution_by_baseline_error': contrib,
                        'weighted_total_mae': {'baseline': mean(abs(r['eH']) * r['weightTotal'] for r in j2),
                                               'combination': mean(abs(r['eM']) * r['weightTotal'] for r in j2)},
                        'listing_weighted_mae': {'baseline': lw('eH'), 'combination': lw('eM'), 'relative': lw('eM') / lw('eH') - 1},
                        'mae_optimal_weight': min(((l / 1000, mean(abs(l / 1000 * r['eV'] + (1 - l / 1000) * r['eH']) for r in j2)) for l in range(0, 1001)),
                                                  key=lambda x: x[1])}

    # H12. Display rules.
    def rule_summary(s, use_history):
        e = [r['eH'] if use_history(r) else r['eM'] for r in s]
        return {'n': len(s), 'fallbacks': sum(use_history(r) for r in s), 'mae': mean(abs(x) for x in e),
                'relative_to_baseline': mean(abs(x) for x in e) / mae(s, 'eH') - 1, 'relative_combination': mae(s, 'eM') / mae(s, 'eH') - 1}
    thin = lambda r: r['level'] < 30 and r['applicant_count'] / max(r['official_quota'], 1) < 3
    under = lambda r: r['quota_status'] not in ('filled', '', None)
    rules_ = {'thin low level': thin, 'simulated underfilled': under, 'either': lambda r: thin(r) or under(r)}
    parts = {'all': lambda r: True, 'below 30': lambda r: r['level'] < 30, 'below 30, south, east and Kinmen':
             lambda r: r['level'] < 30 and r['region'] in ('south', 'east_and_kinmen'), 'private': lambda r: not public(r),
             'officially underfilled': lambda r: r['official_under']}
    out['display_rules'] = {name: {p: rule_summary([r for r in j2 if g(r)], f) for p, g in parts.items()} for name, f in rules_.items()}
    out['display_rules']['quota_status_values'] = sorted({str(r['quota_status']) for r in j2})

    # H13. Stricter release sets.
    def headline(s):
        flagged = [r for r in s if abs(r['S']) >= 1 and r['D'] != 0]
        return {'n': len(s), 'institutions': len({r['school'] for r in s}), 'relative': mae(s, 'eM') / mae(s, 'eH') - 1,
                'gain': gain(s), 'agreement': mean((r['S'] > 0) == (r['D'] > 0) for r in flagged), 'private_share': mean(not public(r) for r in s)}
    out['release'] = {'all': headline(j2), 'confidence normal': headline([r for r in j2 if r['confidence'] == 'normal']),
                      'at least 10 listings': headline([r for r in j2 if r['applicant_count'] >= 10]),
                      'at least 20 listings': headline([r for r in j2 if r['applicant_count'] >= 20]),
                      'confidence_values': sorted({str(r['confidence']) for r in j2})}

    # H14. Officially filled and underfilled departments.
    def measures(s):
        return {'n': len(s), 'mae_baseline': mae(s, 'eH'), 'mae_v3': mae(s, 'eV'), 'mae_combination': mae(s, 'eM'),
                'gain': gain(s), 'interval': ci(s, gain) if len({r['school'] for r in s}) >= 5 else None}
    out['filled'] = {'filled': measures([r for r in j2 if not r['official_under']]), 'underfilled': measures([r for r in j2 if r['official_under']])}

    # H15. Between-institution heterogeneity by REML.
    by = {}
    for r in j2:
        by.setdefault(r['school'], []).append(abs(r['eM']) - abs(r['eH']))
    stats_ = [(statistics.fmean(v), statistics.variance(v) / len(v)) for v in by.values() if len(v) >= 2 and statistics.variance(v) > 0]
    fit = reml([m for m, _ in stats_], [v for _, v in stats_])
    t = _t_quantile(0.975, len(stats_) - 2)
    ses = [math.sqrt(v) for _, v in stats_]
    ms = [m for m, _ in stats_]
    mm, ms_ = statistics.fmean(ms), statistics.fmean(ses)
    corr = sum((a - mm) * (b - ms_) for a, b in zip(ms, ses)) / math.sqrt(sum((a - mm) ** 2 for a in ms) * sum((b - ms_) ** 2 for b in ses))
    out['heterogeneity'] = {'institutions': len(stats_), 'reml_mean': fit['mu'], 'reml_tau': fit['tau'],
                            'prediction_interval': [fit['mu'] - t * math.sqrt(fit['tau'] ** 2 + fit['se_mu'] ** 2),
                                                    fit['mu'] + t * math.sqrt(fit['tau'] ** 2 + fit['se_mu'] ** 2)],
                            'correlation_gain_with_standard_error': corr}

    # H16. Partial pooling of subgroup gains (normal-normal, REML; standard errors from institution resamples).
    def pooled(cells):
        est = []
        for name, s in cells:
            draws = cluster_draws(s, gain, reps=1000)
            est.append((name, len(s), gain(s), statistics.pstdev(draws)))
        fit_ = reml([e[2] for e in est], [e[3] ** 2 for e in est])
        res = {}
        for name, n, g, se in est:
            b = fit_['tau'] ** 2 / (fit_['tau'] ** 2 + se ** 2) if fit_['tau'] > 0 else 0.0
            res[name] = {'n': n, 'raw': g, 'se': se, 'pooled': fit_['mu'] + b * (g - fit_['mu'])}
        return {'tau': fit_['tau'], 'mean': fit_['mu'], 'cells': res}
    region_cells = [(f'{g} {"below" if lowp else "at least"} 30', [r for r in j2 if r['region'] == g and (r['level'] < 30) == lowp])
                    for g in ('north', 'central', 'south', 'east_and_kinmen') for lowp in (True, False)]
    structure_cells = [('subjects changed', [r for r in j2 if r['rule'] == 'subjects']),
                       ('multipliers changed', [r for r in j2 if r['rule'] == 'multipliers']),
                       ('rules unchanged, quota changed', [r for r in j2 if r['rule'] == 'unchanged' and r['dq'] not in (None, 0)]),
                       ('rules and quota unchanged', [r for r in j2 if r['rule'] == 'unchanged' and r['dq'] == 0])]
    out['pooling'] = {'region_by_level': pooled(region_cells), 'structure': pooled(structure_cells)}

    # H17. No-history departments: a synthetic value from the institution's other departments.
    no_hist = [r for r in rows if r['baseline'] is None and r['v3'] is not None and r['actual'] and r['actual'] > 0]
    med_level = {}
    for r in j2:
        med_level.setdefault(r['school'], []).append(r['baseline'] / r['weightTotal'])
    res = []
    for r in no_hist:
        if r['school'] not in med_level:
            continue
        syn = statistics.median(med_level[r['school']]) * r['weightTotal']
        res.append({'v3': (r['v3'] - r['actual']) / r['weightTotal'], 'syn': (syn - r['actual']) / r['weightTotal']})
    out['no_history'] = {'n': len(res), 'mae_v3': mean(abs(x['v3']) for x in res), 'bias_v3': mean(x['v3'] for x in res),
                         'mae_synthetic': mean(abs(x['syn']) for x in res),
                         'mae_mix_0.4': mean(abs(0.4 * x['v3'] + 0.6 * x['syn']) for x in res),
                         'mae_mix_0.6': mean(abs(0.6 * x['v3'] + 0.4 * x['syn']) for x in res)}

    # H18. The gain when the simulation's level relative to history varies across years (illustration).
    def shifted_gain(s):
        return mean(abs(LAMBDA * (r['eV'] + s) + (1 - LAMBDA) * r['eH']) - abs(r['eH']) for r in j2)
    nodes = [(-3 + 6 * i / 600) for i in range(601)]
    ys = {}
    for sd in (0.5, 0.8):
        w = [math.exp(-0.5 * (x / sd) ** 2) for x in nodes]
        W = sum(w)
        vals = sorted((shifted_gain(x), wi / W) for x, wi in zip(nodes, w))
        acc, q10, q90_ = 0.0, None, None
        for v, p in vals:
            acc += p
            if q10 is None and acc >= 0.1:
                q10 = v
            if q90_ is None and acc >= 0.9:
                q90_ = v
        ys[f'sd {sd}'] = {'expected_gain': sum(shifted_gain(x) * wi / W for x, wi in zip(nodes, w)), 'q10': q10, 'q90': q90_}
    out['year_shift'] = ys

    output_path('sixth-review.json').write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(out, indent=1, ensure_ascii=False)[:3000])


if __name__ == '__main__':
    main()
