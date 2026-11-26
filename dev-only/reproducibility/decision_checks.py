"""Decision-relevant errors and data checks from released data (exploratory; added after a third review).

Sections:
* decision: MAE, RMSE, median absolute error, bias and the shares of departments whose official cutoff
  lies strictly within one grade of the prediction, at least one grade above it, or at least one grade below it,
  for the historical baseline, v3 and the fixed combination, with institution-cluster intervals;
* flags: direction agreement, the share moving by at least the threshold in the flagged direction and
  the Gerrity skill score of three-category flags, for raw and self-centred simulated departures
  (centring subtracts the mean simulated departure, which needs no outcome), across thresholds;
* calibration: the same checks for each calibration setting of the granularity file;
* shrinkage: the squared-error-optimal weight on v3 by listing stratum, and stratum weights fitted
  leaving one institution out, compared with the fixed weight;
* fallbacks: departments without history and departments the simulation leaves underfilled;
* linkage: the frozen archive's cross-year links against a later archive's (history-2024.csv);
* percentile scale: the fixed combination formed on the percentile-rank scale, as in the backtest;
* market: listings per record, the mass ledger, and simulated against official filling status.
Writes decision-checks.json.
"""
import csv
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, load_rows, common_rows, input_path, output_path  # noqa: E402
from demand_signal import spearman  # noqa: E402
from history_checks import cluster_interval  # noqa: E402
from reproduce_baseline import curve, weighted_pr, weighted_score  # noqa: E402

LAMBDA = 0.4
BINS = ((0, 20), (20, 40), (40, 80), (80, 160), (160, 10 ** 9))
THRESHOLDS = (0.5, 1.0, 1.5, 2.0, 3.0)
REGISTRANTS = 33071


def e(r, value):
    return (value - r['actual']) / r['weightTotal']


STATS = {
    'mae': lambda es: statistics.fmean(abs(x) for x in es),
    'rmse': lambda es: math.sqrt(statistics.fmean(x * x for x in es)),
    'median_absolute_error': lambda es: statistics.median(abs(x) for x in es),
    # Strictly within one grade, so that the three shares partition the departments.
    'within_one_grade': lambda es: statistics.fmean(abs(x) < 1 for x in es),
    'official_at_least_one_grade_above': lambda es: statistics.fmean(x <= -1 for x in es),
    'official_at_least_one_grade_below': lambda es: statistics.fmean(x >= 1 for x in es),
}


def summarize(rows, pred):
    es = [e(r, pred(r)) for r in rows]
    out = {'n': len(rows), 'bias': statistics.fmean(es)}
    out.update({k: f(es) for k, f in STATS.items()})
    return out


def difference(rows, pa, pb, stat):
    f = lambda s: stat([e(r, pa(r)) for r in s]) - stat([e(r, pb(r)) for r in s])
    return {'difference': f(rows), 'interval': cluster_interval(rows, f)}


def mae_difference(rows, pa, pb):
    out = difference(rows, pa, pb, STATS['mae'])
    out['relative'] = out['difference'] / STATS['mae']([e(r, pb(r)) for r in rows])
    return out


base = lambda r: r['baseline']
v3 = lambda r: r['v3']
mix = lambda r: LAMBDA * r['v3'] + (1 - LAMBDA) * r['baseline']


def decision(j2):
    out = {}
    strata = {'all': j2,
              'fewer_than_20_listings': [r for r in j2 if r['applicant_count'] < 20],
              'at_least_20_listings': [r for r in j2 if r['applicant_count'] >= 20],
              'historical_level_below_30': [r for r in j2 if r['baseline'] / r['weightTotal'] < 30]}
    for name, rows in strata.items():
        entry = {'historical': summarize(rows, base), 'v3': summarize(rows, v3), 'combination': summarize(rows, mix)}
        entry['combination_minus_historical'] = {k: difference(rows, mix, base, f) for k, f in STATS.items()}
        if name == 'all':
            entry['v3_minus_historical'] = {k: difference(rows, v3, base, STATS[k])
                                            for k in ('median_absolute_error', 'within_one_grade', 'rmse')}
        out[name] = entry
    return out


def gerrity(table):
    """Gerrity (1992) skill score; table[f][o] counts with categories ordered low, middle, high."""
    k = len(table)
    n = sum(map(sum, table))
    p = [sum(table[f][o] for f in range(k)) / n for o in range(k)]
    cum = [sum(p[:r + 1]) for r in range(k - 1)]
    if any(c <= 0 or c >= 1 for c in cum):
        return None
    a = [(1 - c) / c for c in cum]
    s = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(i, k):
            if i == j:
                s[i][i] = (sum(1 / a[r] for r in range(i)) + sum(a[r] for r in range(i, k - 1))) / (k - 1)
            else:
                s[i][j] = s[j][i] = (sum(1 / a[r] for r in range(i)) - (j - i) + sum(a[r] for r in range(j, k - 1))) / (k - 1)
    return sum(table[f][o] / n * s[f][o] for f in range(k) for o in range(k))


def flag_summary(d, s, delta):
    cls = lambda v: 2 if v >= delta else (0 if v <= -delta else 1)
    table = [[0] * 3 for _ in range(3)]
    for di, si in zip(d, s):
        table[cls(si)][cls(di)] += 1
    flagged = [(di, si) for di, si in zip(d, s) if abs(si) >= delta and di != 0]
    moved = [(di, si) for di, si in zip(d, s) if abs(si) >= delta]
    return {'flagged': len(moved),
            'direction_agreement': sum((si > 0) == (di > 0) for di, si in flagged) / len(flagged) if flagged else None,
            'moved_by_threshold_in_flagged_direction': (sum((di >= delta) if si > 0 else (di <= -delta) for di, si in moved)
                                                         / len(moved)) if moved else None,
            'hot_precision': table[2][2] / sum(table[2]) if sum(table[2]) else None,
            'cold_precision': table[0][0] / sum(table[0]) if sum(table[0]) else None,
            'gerrity_skill_score': gerrity(table)}


def flags(j2):
    d = [(r['actual'] - r['baseline']) / r['weightTotal'] for r in j2]
    s = [(r['v3'] - r['baseline']) / r['weightTotal'] for r in j2]
    mean_s = statistics.fmean(s)
    centred = [x - mean_s for x in s]
    return {'mean_simulated_departure': mean_s,
            'raw': {str(t): flag_summary(d, s, t) for t in THRESHOLDS},
            'self_centred': {str(t): flag_summary(d, centred, t) for t in THRESHOLDS},
            'combination_departure_0.4S': {str(t): flag_summary(d, [LAMBDA * x for x in s], t) for t in THRESHOLDS}}


def calibration(rows):
    path = input_path('weighting-granularity-departments.csv')
    with path.open(encoding='utf-8', newline='') as handle:
        table = {int(r['gid']): {k: (float(v) if v != '' else None) for k, v in r.items() if k != 'gid'}
                 for r in csv.DictReader(handle)}
    configs = ('uniform', 'ew2', 'ew3', 'ew6', 'ew61', 'eq3')
    j2 = common_rows(rows, ('v3', 'baseline'))
    fixed = [r for r in j2 if all(table[r['gid']][c] is not None for c in configs)]
    base_mae = statistics.fmean(abs(e(r, r['baseline'])) for r in fixed)
    d = [(r['actual'] - r['baseline']) / r['weightTotal'] for r in fixed]
    out = {'n': len(fixed), 'baseline_mae': base_mae, 'configs': {}}
    for c in configs:
        g = lambda r, c=c: table[r['gid']][c]
        s = [(g(r) - r['baseline']) / r['weightTotal'] for r in fixed]
        mean_s = statistics.fmean(s)
        centred_v3 = lambda r, c=c, m=mean_s: table[r['gid']][c] - m * r['weightTotal']
        low = [r for r in fixed if r['baseline'] / r['weightTotal'] < 30]
        out['configs'][c] = {
            'mean_simulated_departure': mean_s,
            'mae': statistics.fmean(abs(e(r, g(r))) for r in fixed),
            'mae_self_centred': statistics.fmean(abs(e(r, centred_v3(r))) for r in fixed),
            'combination_gain': statistics.fmean(abs(e(r, LAMBDA * g(r) + (1 - LAMBDA) * r['baseline'])) for r in fixed) / base_mae - 1,
            'combination_gain_self_centred': statistics.fmean(
                abs(e(r, LAMBDA * centred_v3(r) + (1 - LAMBDA) * r['baseline'])) for r in fixed) / base_mae - 1,
            'direction_agreement': flag_summary(d, s, 1.0)['direction_agreement'],
            'direction_agreement_self_centred': flag_summary(d, [x - mean_s for x in s], 1.0)['direction_agreement'],
            'spearman_S_D': spearman(s, d),
            'bias_historical_level_below_30': statistics.fmean(e(r, g(r)) for r in low),
            'n_historical_level_below_30': len(low)}
    return out


def stratum(r):
    if r['quota_status'] == 'underfilled':
        return 'underfilled'
    for lo, hi in BINS:
        if lo <= r['applicant_count'] < hi:
            return f'{lo}+' if hi > 10 ** 8 else f'{lo}-{hi - 1}'


def optimal_weight(rows):
    eh = [e(r, r['baseline']) for r in rows]
    g = [e(r, r['v3']) - x for r, x in zip(rows, eh)]
    den = sum(x * x for x in g)
    return -sum(a * b for a, b in zip(eh, g)) / den if den else None


def shrinkage(j2):
    out = {'by_stratum': {}}
    for name in sorted({stratum(r) for r in j2}):
        sub = [r for r in j2 if stratum(r) == name]
        out['by_stratum'][name] = {'n': len(sub), 'optimal_weight': optimal_weight(sub),
                                   'interval': cluster_interval(sub, optimal_weight)}
    out['all'] = {'n': len(j2), 'optimal_weight': optimal_weight(j2)}
    for r in j2:
        r['_stratum'] = stratum(r)
    for school in sorted({r['school'] for r in j2}):
        train = [r for r in j2 if r['school'] != school]
        weights = {}
        for name in {r['_stratum'] for r in j2}:
            w = optimal_weight([r for r in train if r['_stratum'] == name])
            weights[name] = min(1.0, max(0.0, w if w is not None else LAMBDA))
        for r in j2:
            if r['school'] == school:
                r['_lambda'] = weights[r['_stratum']]
                r['_mix_stratum'] = r['_lambda'] * r['v3'] + (1 - r['_lambda']) * r['baseline']
    strat = lambda r: r['_mix_stratum']
    out['leave_one_institution_out'] = {
        'mae': statistics.fmean(abs(e(r, strat(r))) for r in j2),
        'mae_fixed': statistics.fmean(abs(e(r, mix(r))) for r in j2),
        'mae_difference': difference(j2, strat, mix, STATS['mae']),
        'rmse_difference': difference(j2, strat, mix, STATS['rmse'])}
    return out


def fallbacks(rows, j2):
    levels = {}
    for r in rows:
        if r['baseline'] is not None:
            levels.setdefault(r['school'], []).append(r['baseline'] / r['weightTotal'])
    inst = {k: statistics.fmean(v) for k, v in levels.items()}
    nohist = [r for r in rows if r['no_history_in_snapshot'] and r['v3'] is not None and r['school'] in inst]
    inst_pred = lambda r: inst[r['school']] * r['weightTotal']
    mixed = lambda r: LAMBDA * r['v3'] + (1 - LAMBDA) * inst_pred(r)
    out = {'no_history': {'n': len(nohist), 'v3': STATS['mae']([e(r, r['v3']) for r in nohist]),
                          'institution_mean': STATS['mae']([e(r, inst_pred(r)) for r in nohist]),
                          'combination_with_institution_mean': STATS['mae']([e(r, mixed(r)) for r in nohist]),
                          'combination_minus_v3': difference(nohist, mixed, v3, STATS['mae'])}}
    under = [r for r in j2 if r['quota_status'] == 'underfilled']
    rule = lambda r: r['baseline'] if r['quota_status'] == 'underfilled' else mix(r)
    out['simulation_underfilled'] = {
        'n': len(under), 'v3': STATS['mae']([e(r, r['v3']) for r in under]),
        'historical': STATS['mae']([e(r, r['baseline']) for r in under]),
        'combination': STATS['mae']([e(r, mix(r)) for r in under]),
        'all_departments_with_history_where_underfilled': STATS['mae']([e(r, rule(r)) for r in j2]),
        'rule_minus_combination': difference(j2, rule, mix, STATS['mae'])}
    return out


def linkage(rows, j2):
    with (PAPER / 'data/history-2024.csv').open(newline='') as f:
        relinked = {int(r['gid']): float(r['relinked_baseline']) for r in csv.DictReader(f) if r['relinked_baseline']}
    nohist = [r for r in rows if r['no_history_in_snapshot']]
    added = [dict(r, baseline=relinked[r['gid']]) for r in rows
             if r['gid'] in relinked and r['baseline'] is None and r['v3'] is not None]
    out = {'relinked_departments': len(relinked), 'relinked_with_released_v3': len(added),
           'no_history_departments': len(nohist),
           'no_history_v3_mae_relinked': STATS['mae']([e(r, r['v3']) for r in rows if r['gid'] in relinked and r['v3'] is not None]),
           'no_history_v3_mae_new': STATS['mae']([e(r, r['v3']) for r in nohist if r['gid'] not in relinked and r['v3'] is not None]),
           'no_history_v3_n_new': sum(1 for r in nohist if r['gid'] not in relinked and r['v3'] is not None)}
    unlinked = [r for r in j2 if r['gid'] == 934]
    out['department_934'] = {'in_J2': bool(unlinked), 'v3_error': e(unlinked[0], unlinked[0]['v3']) if unlinked else None,
                             'baseline_error': e(unlinked[0], unlinked[0]['baseline']) if unlinked else None}
    sets = {'J2_without_934': [r for r in j2 if r['gid'] != 934]}
    sets['J2_without_934_with_relinked'] = sets['J2_without_934'] + added
    sets['relinked_only'] = added
    for name, sub in sets.items():
        d = [(r['actual'] - r['baseline']) / r['weightTotal'] for r in sub]
        s = [(r['v3'] - r['baseline']) / r['weightTotal'] for r in sub]
        out[name] = {'n': len(sub), 'historical': STATS['mae']([e(r, r['baseline']) for r in sub]),
                     'v3': STATS['mae']([e(r, r['v3']) for r in sub]), 'combination': STATS['mae']([e(r, mix(r)) for r in sub]),
                     'combination_minus_historical': mae_difference(sub, mix, base) if len(sub) > 40 else None,
                     'direction_agreement': flag_summary(d, s, 1.0)['direction_agreement']}
    return out


def percentile_scale(j2):
    inputs = json.loads((PAPER / 'data/baseline-inputs.json').read_text())
    items = {d['gid']: d['items'] for d in inputs['departments']}
    dist = {k: curve(v) for k, v in inputs['distributions'].items()}
    sub = []
    for r in j2:
        pv = weighted_pr(items[r['gid']], 2026, r['v3'], dist)
        ph = weighted_pr(items[r['gid']], 2026, r['baseline'], dist)
        if pv is not None and ph is not None:
            sub.append(dict(r, mix_pr=weighted_score(items[r['gid']], 2026, LAMBDA * pv + (1 - LAMBDA) * ph, dist)))
    pr = lambda r: r['mix_pr']
    return {'n': len(sub), 'historical': STATS['mae']([e(r, r['baseline']) for r in sub]),
            'score_scale_combination': STATS['mae']([e(r, mix(r)) for r in sub]),
            'percentile_scale_combination': STATS['mae']([e(r, pr(r)) for r in sub]),
            'percentile_minus_historical': mae_difference(sub, pr, base),
            'mean_absolute_gap_between_scales': statistics.fmean(abs(pr(r) - mix(r)) / r['weightTotal'] for r in sub)}


def market(rows, j2):
    ledger = json.loads((PAPER / 'data/market-diagnostics.json').read_text())['ledger']['accounts']
    supply = ledger['supply']['mass']
    unallocated = ledger['noPreferences']['mass'] + ledger['exhausted']['mass']
    audit = {int(r['gid']): int(r['admitted_including_extra'])
             for r in csv.DictReader((PAPER / 'data/official-rules-audit.csv').open())}
    released = [r for r in rows if r['quota_status']]
    official_under = lambda r: audit[r['gid']] < r['official_quota']
    confusion = {}
    for r in released:
        key = f"{r['quota_status']}|{'official_underfilled' if official_under(r) else 'official_filled'}"
        confusion[key] = confusion.get(key, 0) + 1
    by_official = {}
    for label, keep in (('official_underfilled', official_under), ('official_filled', lambda r: not official_under(r))):
        sub = [r for r in j2 if keep(r)]
        by_official[label] = {'n': len(sub), 'historical': STATS['mae']([e(r, r['baseline']) for r in sub]),
                              'v3': STATS['mae']([e(r, r['v3']) for r in sub]),
                              'combination': STATS['mae']([e(r, mix(r)) for r in sub])}
    return {'records': 4627, 'listings_of_evaluated_departments_per_record': sum(r['applicant_count'] for r in rows) / 4627,
            'mass_supply': supply, 'mass_unallocated': unallocated, 'unallocated_share': unallocated / supply,
            'excess_over_registrants': supply - REGISTRANTS,
            'unallocated_beyond_excess': unallocated - (supply - REGISTRANTS),
            'unallocated_beyond_excess_share_of_registrants': (unallocated - (supply - REGISTRANTS)) / REGISTRANTS,
            'filling_status_released': confusion,
            'official_underfilled_among_evaluated': sum(official_under(r) for r in rows),
            'error_by_official_filling_status': by_official}


def main():
    rows = load_rows()
    j2 = common_rows(rows, ('v3', 'baseline'))
    out = {'note': 'exploratory; added after the third round of simulated pre-submission reviews', 'n_J2': len(j2),
           'decision': decision(j2), 'flags': flags(j2), 'calibration': calibration(rows),
           'shrinkage': shrinkage([dict(r) for r in j2]), 'fallbacks': fallbacks(rows, j2),
           'linkage': linkage(rows, j2), 'percentile_scale': percentile_scale(j2), 'market': market(rows, j2)}
    output_path('decision-checks.json').write_text(json.dumps(out, indent=2) + '\n')
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
