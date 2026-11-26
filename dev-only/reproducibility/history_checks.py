"""Checks added after a pre-submission review (exploratory; not in the dated analysis plans).

Reads data/department-benchmark.csv and data/history-2024.csv (public 2024 data, built by
prepare_history.py), and writes data/history-checks.json.

  1. A two-year history: the 2024 cutoff converted to 2026 (H24) and the mean of H24 and the
     baseline (H25), alone and combined with the simulation.
  2. The older history's departure from the baseline, R = (H24 - H25) / B, as a placebo signal.
  3. Encompassing regressions of D on S with two-year reversion R and the 2025->2026 quota change.
  4. A rival fitted to 2026 outcomes with leave-one-institution-out cross-fitting, using only
     history, quota and listing information, with and without S.
  5. Hot and cold events after removing the baseline's level bias, estimated ex ante from a
     2024->2025 backtest of the baseline method, with 3x3 tables and directional-accuracy tests.
  6. Departments whose subject rules changed between 2025 and 2026, reported separately.
  7. Diebold-Mariano statistics with institution-clustered variance; MAE-optimal weight.
The last output saved before the registration deadline is summarized by archived_run_summary.py.
"""
import csv
import json
import math
import os
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, REPETITIONS, SEED, load_rows, common_rows, input_path, output_path  # noqa: E402
from demand_signal import auroc, spearman  # noqa: E402
from exploratory_checks import ols, partial_rank_corr, features  # noqa: E402

DELTA = 1.0
LAMBDA = 0.4
REPS = int(os.environ.get('HISTORY_CHECK_REPS', REPETITIONS))  # for quick tests only


def load_history():
    out = {}
    with (PAPER / 'data/history-2024.csv').open(newline='') as f:
        for r in csv.DictReader(f):
            num = lambda k: float(r[k]) if r[k] not in ('', 'None') else None
            out[int(r['gid'])] = {'h24': num('h24'), 'b25': num('b25'), 'cutoff_2025': num('cutoff_2025'),
                                  'weight_total_2025': num('weight_total_2025'), 'quota_2025': num('quota_2025'),
                                  'quota_2024': num('quota_2024')}
    return out


def cluster_interval(rows, stat, repetitions=REPS, seed=SEED):
    groups = {}
    for r in rows:
        groups.setdefault(r['school'], []).append(r)
    keys = list(groups)
    rng = random.Random(seed)
    vals = []
    for _ in range(repetitions):
        sample = []
        for _ in keys:
            sample.extend(groups[keys[rng.randrange(len(keys))]])
        v = stat(sample)
        if v is not None:
            vals.append(v)
    vals.sort()
    return [vals[int(.025 * len(vals))], vals[int(.975 * len(vals))]]


def err(r, key):
    return (r[key] - r['actual']) / r['weightTotal']


def mae(rows, key):
    return statistics.fmean(abs(err(r, key)) for r in rows)


def mean_diff(rows, first, second):
    return statistics.fmean(abs(err(r, first)) - abs(err(r, second)) for r in rows)


def diff_with_interval(rows, first, second):
    return {'difference': mean_diff(rows, first, second),
            'relative': mean_diff(rows, first, second) / mae(rows, second),
            'interval': cluster_interval(rows, lambda s: mean_diff(s, first, second))}


def dm_clustered(rows, first, second, squared=False):
    """Diebold-Mariano type t statistic with institution-clustered variance (CR1)."""
    loss = (lambda e: e * e) if squared else abs
    d = [loss(err(r, first)) - loss(err(r, second)) for r in rows]
    mean = statistics.fmean(d)
    sums = {}
    for r, v in zip(rows, d):
        sums[r['school']] = sums.get(r['school'], 0.0) + (v - mean)
    g, n = len(sums), len(d)
    var = g / (g - 1) * sum(s * s for s in sums.values()) / (n * n)
    return {'mean_loss_difference': mean, 't': mean / math.sqrt(var), 'clusters': g}


def detection(d, s, delta=DELTA):
    """Precision, recall, Peirce skill score, direction agreement and a 3x3 table."""
    n = len(d)
    cls = lambda v: 'hot' if v >= delta else ('cold' if v <= -delta else 'neutral')
    table = {a: {b: 0 for b in ('hot', 'neutral', 'cold')} for a in ('hot', 'neutral', 'cold')}
    for di, si in zip(d, s):
        table[cls(si)][cls(di)] += 1
    out = {'n': n, 'table_flag_by_event': table}
    for side in ('hot', 'cold'):
        flags = sum(table[side].values())
        events = sum(table[f][side] for f in table)
        tp = table[side][side]
        fp_rate = (flags - tp) / (n - events) if n - events else None
        out[side] = {'flags': flags, 'events': events, 'precision': tp / flags if flags else None,
                     'recall': tp / events if events else None,
                     'peirce': (tp / events - fp_rate) if events and fp_rate is not None else None}
    flagged = [(di, si) for di, si in zip(d, s) if abs(si) >= delta and di != 0]
    out['flagged'] = len(flagged)
    out['direction_agreement'] = sum((si > 0) == (di > 0) for di, si in flagged) / len(flagged)
    # Pesaran-Timmermann (1992) test of directional accuracy on the flagged departments.
    m = len(flagged)
    py = sum(di > 0 for di, _ in flagged) / m
    px = sum(si > 0 for _, si in flagged) / m
    p_hat = out['direction_agreement']
    p_star = py * px + (1 - py) * (1 - px)
    v_p = p_star * (1 - p_star) / m
    v_star = ((2 * py - 1) ** 2 * px * (1 - px) / m + (2 * px - 1) ** 2 * py * (1 - py) / m
              + 4 * py * px * (1 - py) * (1 - px) / m ** 2)
    out['pesaran_timmermann'] = {'expected_agreement_if_independent': p_star,
                                 'statistic': (p_hat - p_star) / math.sqrt(v_p - v_star)}
    out['mean_S_flagged_hot'] = statistics.fmean(si for si in s if si >= delta)
    out['mean_D_flagged_hot'] = statistics.fmean(di for di, si in zip(d, s) if si >= delta)
    out['mean_S_flagged_cold'] = statistics.fmean(si for si in s if si <= -delta)
    out['mean_D_flagged_cold'] = statistics.fmean(di for di, si in zip(d, s) if si <= -delta)
    return out


def extended_features(rows):
    f = features(rows)
    f['R'] = [((r['h24'] - r['baseline']) / r['weightTotal']) if r['h24'] is not None else 0.0 for r in rows]
    f['R_missing'] = [0.0 if r['h24'] is not None else 1.0 for r in rows]
    f['quota_change'] = [math.log(r['official_quota'] / r['quota_2025']) if r['quota_2025'] else 0.0 for r in rows]
    f['quota_missing'] = [0.0 if r['quota_2025'] else 1.0 for r in rows]
    return f


HISTORY_ONLY = ('level', 'level_sq', 'school_gap', 'rules_changed', 'quota_change', 'quota_missing', 'R', 'R_missing')
WITH_POPULARITY = HISTORY_ONLY + ('popularity',)


def cross_fit(rows, names):
    """Leave-one-institution-out OLS predictions of D; returns predicted cutoffs."""
    f = extended_features(rows)
    preds = [None] * len(rows)
    for school in {r['school'] for r in rows}:
        train = [k for k, r in enumerate(rows) if r['school'] != school]
        test = [k for k, r in enumerate(rows) if r['school'] == school]
        use = varying(f, names, train)
        beta, _ = ols([[f[n][k] for k in train] for n in use], [f['D'][k] for k in train])
        for k in test:
            d_hat = beta[0] + sum(b * f[n][k] for b, n in zip(beta[1:], use))
            preds[k] = rows[k]['baseline'] + rows[k]['weightTotal'] * d_hat
    return preds


def varying(f, names, index=None):
    """Drop indicator columns that are constant in the data used for fitting."""
    pick = (lambda col: col) if index is None else (lambda col: [col[k] for k in index])
    return [n for n in names if len(set(pick(f[n]))) > 1]


def encompassing(rows, controls):
    f = extended_features(rows)
    controls = varying(f, controls)
    ctrl = [f[c] for c in controls]
    b_c, r2_c = ols(ctrl, f['D'])
    b_f, r2_f = ols([f['S']] + ctrl, f['D'])
    return {'n': len(rows), 'r2_controls_only': r2_c, 'r2_S_and_controls': r2_f, 'delta_r2_from_S': r2_f - r2_c,
            'coef_S_with_controls': b_f[1], 'coef_controls_with_S': dict(zip(controls, b_f[2:])),
            'coef_controls_without_S': dict(zip(controls, b_c[1:])),
            'partial_spearman_D_S_given_controls': partial_rank_corr(f['D'], f['S'], ctrl)}


def main():
    rows = load_rows()
    history = load_history()
    for r in rows:
        r.update(history[r['gid']])
    j2 = common_rows(rows, ('v3', 'baseline'))
    out = {'note': 'exploratory; added after a pre-submission review; not in the dated analysis plans',
           'n_J2': len(j2), 'lambda': LAMBDA, 'delta': DELTA}

    # 1. Two-year history.
    j2h = [r for r in j2 if r['h24'] is not None]
    for r in rows:
        r['h_mean'] = (r['h24'] + r['baseline']) / 2 if r['h24'] is not None and r['baseline'] is not None else r['baseline']
        r['mix'] = LAMBDA * r['v3'] + (1 - LAMBDA) * r['baseline'] if r['v3'] is not None and r['baseline'] is not None else None
        r['mix_h_mean'] = LAMBDA * r['v3'] + (1 - LAMBDA) * r['h_mean'] if r['v3'] is not None and r['h_mean'] is not None else None
    out['two_year_history'] = {
        'n': len(j2h), 'schools': len({r['school'] for r in j2h}),
        'mae': {k: mae(j2h, k) for k in ('baseline', 'h24', 'h_mean', 'v3', 'mix', 'mix_h_mean')},
        'bias': {k: statistics.fmean(err(r, k) for r in j2h) for k in ('baseline', 'h24', 'h_mean', 'v3', 'mix', 'mix_h_mean')},
        'h_mean_minus_baseline': diff_with_interval(j2h, 'h_mean', 'baseline'),
        'mix_minus_h_mean': diff_with_interval(j2h, 'mix', 'h_mean'),
        'mix_h_mean_minus_h_mean': diff_with_interval(j2h, 'mix_h_mean', 'h_mean'),
        'corr_errors_v3_h_mean': statistics.correlation([err(r, 'v3') for r in j2h], [err(r, 'h_mean') for r in j2h]),
    }

    # 2. Placebo departure from the older history.
    f = extended_features(j2h)
    hot = [d >= DELTA for d in f['D']]
    cold = [d <= -DELTA for d in f['D']]
    out['placebo'] = {}
    for name in ('S', 'R'):
        sig = f[name]
        det = detection(f['D'], sig)
        out['placebo'][name] = {
            'spearman_with_D': spearman(f['D'], sig), 'flagged': det['flagged'],
            'direction_agreement': det['direction_agreement'],
            'auroc_hot': auroc([s for s, h in zip(sig, hot) if h], [s for s, h in zip(sig, hot) if not h]),
            'auroc_cold': auroc([-s for s, c in zip(sig, cold) if c], [-s for s, c in zip(sig, cold) if not c])}
    out['placebo']['corr_S_R'] = statistics.correlation(f['S'], f['R'])
    out['placebo']['spearman_D_S_given_R'] = partial_rank_corr(f['D'], f['S'], [f['R']])

    # 2b. How large are transitory shocks in the 2025 cutoffs? Write each cutoff as a persistent
    #     level plus an independent transitory shock e_y. Then cov(D, R) = var(e_2025), and the
    #     baseline's 2025 backtest error and its 2026 error have covariance -var(e_2025), when
    #     persistent changes are uncorrelated across years. Shared transitory error can then
    #     contribute at most var(e_2025) to cov(S, D).
    def transitory(sample):
        g = extended_features(sample)
        both = [k for k, r in enumerate(sample) if r['b25'] is not None and r['cutoff_2025'] and r['weight_total_2025']]
        e25 = [(sample[k]['b25'] - sample[k]['cutoff_2025']) / sample[k]['weight_total_2025'] for k in both]
        e26 = [err(sample[k], 'baseline') for k in both]
        var_d = statistics.variance(g['D'])
        cov_sd = statistics.covariance(g['S'], g['D'])
        v1 = statistics.covariance(g['D'], g['R'])
        v2 = -statistics.covariance(e25, e26)
        return {'var_D': var_d, 'cov_S_D': cov_sd, 'var_transitory_from_R': v1, 'var_transitory_from_backtest': v2,
                'share_of_var_D_from_R': v1 / var_d, 'share_of_var_D_from_backtest': v2 / var_d,
                'share_of_cov_SD_from_R': v1 / cov_sd, 'share_of_cov_SD_from_backtest': v2 / cov_sd}
    tr = transitory(j2h)
    for key in ('share_of_var_D_from_R', 'share_of_var_D_from_backtest', 'share_of_cov_SD_from_R', 'share_of_cov_SD_from_backtest'):
        tr['interval_' + key] = cluster_interval(j2h, lambda s, key=key: transitory(s)[key])
    out['transitory_shocks'] = tr

    # 3. Encompassing with reversion and quota change (all of J2, missing indicators).
    enc = encompassing(j2, WITH_POPULARITY)
    keys = ('delta_r2_from_S', 'coef_S_with_controls', 'partial_spearman_D_S_given_controls')
    groups = {}
    for r in j2:
        groups.setdefault(r['school'], []).append(r)
    schools = list(groups)
    rng = random.Random(SEED)
    draws = {k: [] for k in keys}
    for _ in range(REPS):
        sample = []
        for _ in schools:
            sample.extend(groups[schools[rng.randrange(len(schools))]])
        res = encompassing(sample, WITH_POPULARITY)
        for k in keys:
            draws[k].append(res[k])
    for k in keys:
        v = sorted(draws[k])
        enc['interval_' + k] = [v[int(.025 * len(v))], v[int(.975 * len(v))]]
    out['encompassing_two_year'] = enc

    # 4. Cross-fitted rivals (fitted to 2026 outcomes, so the comparison favours the rival).
    for name, cols in (('rival_history', HISTORY_ONLY), ('rival_history_popularity', WITH_POPULARITY),
                       ('rival_history_popularity_S', ('S',) + WITH_POPULARITY)):
        for r, p in zip(j2, cross_fit(j2, cols)):
            r[name] = p
    out['cross_fitted'] = {
        'features_history': list(HISTORY_ONLY), 'n': len(j2),
        'mae': {k: mae(j2, k) for k in ('baseline', 'mix', 'rival_history', 'rival_history_popularity', 'rival_history_popularity_S')},
        'rival_history_minus_baseline': diff_with_interval(j2, 'rival_history', 'baseline'),
        'rival_popularity_minus_baseline': diff_with_interval(j2, 'rival_history_popularity', 'baseline'),
        'mix_minus_rival_popularity': diff_with_interval(j2, 'mix', 'rival_history_popularity'),
        'adding_S_to_rival': diff_with_interval(j2, 'rival_history_popularity_S', 'rival_history_popularity'),
    }

    # 5. Hot and cold events after removing the baseline's ex-ante level bias.
    back = [r for r in rows if r['b25'] is not None and r['cutoff_2025'] and r['weight_total_2025']]
    bias_backtest = statistics.fmean((r['b25'] - r['cutoff_2025']) / r['weight_total_2025'] for r in back)
    out['baseline_backtest_2025'] = {
        'n': len(back), 'bias': bias_backtest,
        'mae': statistics.fmean(abs(r['b25'] - r['cutoff_2025']) / r['weight_total_2025'] for r in back),
        'note': 'the baseline method applied to 2024 cutoffs, predicting 2025 cutoffs'}
    f = extended_features(j2)
    # Post hoc: remove each departure's own 2026 mean (the level biases of the baseline and of v3).
    mean_d, mean_s = statistics.fmean(f['D']), statistics.fmean(f['S'])
    out['events'] = {'shift_ex_ante': bias_backtest, 'mean_D': mean_d, 'mean_S': mean_s,
                     'share_D_negative': sum(d < 0 for d in f['D']) / len(f['D'])}
    for delta in (1.0, 2.0):
        out['events'][f'delta_{delta:g}'] = {
            'uncentred': detection(f['D'], f['S'], delta),
            'centred_ex_ante': detection([d + bias_backtest for d in f['D']], [s + bias_backtest for s in f['S']], delta),
            'centred_post_hoc': detection([d - mean_d for d in f['D']], [s - mean_s for s in f['S']], delta)}

    # 5b. Where hot flags fall: by historical level band and by sector (public or private).
    bands = ((0, 30), (30, 40), (40, 45), (45, 50), (50, 61))
    out['flags_by_level'] = {}
    for lo, hi in bands:
        idx = [k for k, lv in enumerate(f['level']) if lo <= lv < hi]
        hot_flags = [k for k in idx if f['S'][k] >= DELTA]
        out['flags_by_level'][f'{lo}-{min(hi, 60)}'] = {
            'n': len(idx), 'hot_flags': len(hot_flags),
            'hot_flags_that_were_hot': sum(f['D'][k] >= DELTA for k in hot_flags),
            'hot_flags_that_were_cold': sum(f['D'][k] <= -DELTA for k in hot_flags)}
    public = lambda r: r['school'].startswith(('國立', '臺北市立', '高雄市立', '市立'))
    out['sector'] = {}
    for label, sub in (('public', [r for r in j2 if public(r)]), ('private', [r for r in j2 if not public(r)])):
        out['sector'][label] = {'n': len(sub), 'bias_v3': statistics.fmean(err(r, 'v3') for r in sub),
                                'bias_baseline': statistics.fmean(err(r, 'baseline') for r in sub),
                                'mae_baseline': mae(sub, 'baseline'), 'mae_mix': mae(sub, 'mix'),
                                'mix_minus_baseline': mean_diff(sub, 'mix', 'baseline')}

    # 6. Departments whose subject rules changed between 2025 and 2026.
    out['rules'] = {}
    for label, sub in (('unchanged', [r for r in j2 if r['unchangedWeights']]),
                       ('changed', [r for r in j2 if not r['unchangedWeights']])):
        g = extended_features(sub)
        det = detection(g['D'], g['S'])
        beta, _ = ols([g['S']], g['D'])
        out['rules'][label] = {'n': len(sub), 'mae_baseline': mae(sub, 'baseline'), 'mae_mix': mae(sub, 'mix'),
                               'mix_minus_baseline': mean_diff(sub, 'mix', 'baseline'),
                               'share_of_total_gain': mean_diff(sub, 'mix', 'baseline') * len(sub)
                               / (mean_diff(j2, 'mix', 'baseline') * len(j2)),
                               'direction_agreement': det['direction_agreement'], 'slope_D_on_S': beta[1]}

    # 7. Diebold-Mariano with clustered variance, and the MAE-optimal weight.
    out['diebold_mariano'] = {'absolute': dm_clustered(j2, 'mix', 'baseline'),
                              'squared': dm_clustered(j2, 'mix', 'baseline', squared=True)}
    grid = [k / 1000 for k in range(1001)]
    maes = [statistics.fmean(abs(lam * err(r, 'v3') + (1 - lam) * err(r, 'baseline')) for r in j2) for lam in grid]
    out['mae_optimal_lambda'] = grid[min(range(len(grid)), key=maes.__getitem__)]

    output_path('history-checks.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
