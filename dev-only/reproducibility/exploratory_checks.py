"""Exploratory checks added after the results were known (not in the dated analysis plans).

Reads only the frozen department aggregates in data/department-benchmark.csv and writes
data/exploratory-checks.json. Every statistic here is labelled exploratory in the manuscript.

Checks:
  1. Robustness of the combination to the weight (lambda = 0.3 and 0.5).
  2. A simple popularity index, log((platform listings + 1) / official quota), as a rival
     signal for hot and cold departments, and the partial rank correlation of S and D
     given that index.
  3. Encompassing regressions of the observed departure D on the simulated departure S
     and history-based or popularity controls, with school-cluster intervals.
  4. Magnitude calibration of S (mean S and mean D among flagged departments).
  5. Direction agreement of the departure computed from v2 and Fractional instead of v3.
  6. How much of the interpolation gain a constant level shift of Fractional reproduces.
  7. Error for departments that the simulation leaves underfilled.
  8. History versus v3 on the departments of J2 whose subject rules did not change.
  9. For departments without usable history, v3 against an institution-mean fallback.
"""
import json
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, REPETITIONS, SEED, load_rows, common_rows, output_path  # noqa: E402
from demand_signal import auroc, spearman, detection, mix_difference  # noqa: E402

DELTA = 1.0


def solve(a, b):
    """Gaussian elimination with partial pivoting for a small dense system."""
    n = len(a)
    m = [row[:] + [rhs] for row, rhs in zip(a, b)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        if abs(m[col][col]) < 1e-12:
            raise ValueError('singular design matrix')
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def ols(columns, y):
    """OLS with intercept; returns coefficients (intercept first) and R squared."""
    x = [[1.0] + [col[i] for col in columns] for i in range(len(y))]
    k = len(x[0])
    xtx = [[sum(row[p] * row[q] for row in x) for q in range(k)] for p in range(k)]
    xty = [sum(row[p] * yi for row, yi in zip(x, y)) for p in range(k)]
    beta = solve(xtx, xty)
    fitted = [sum(b * v for b, v in zip(beta, row)) for row in x]
    ybar = sum(y) / len(y)
    sse = sum((yi - fi) ** 2 for yi, fi in zip(y, fitted))
    sst = sum((yi - ybar) ** 2 for yi in y)
    return beta, 1 - sse / sst


def ranks(v):
    order = sorted(range(len(v)), key=lambda k: v[k])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j < len(order) and v[order[j]] == v[order[i]]:
            j += 1
        for k in range(i, j):
            r[order[k]] = (i + j - 1) / 2
        i = j
    return r


def residuals(columns, y):
    beta, _ = ols(columns, y)
    return [yi - (beta[0] + sum(b * col[i] for b, col in zip(beta[1:], columns))) for i, yi in enumerate(y)]


def pearson(x, y):
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return sxy / math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))


def partial_rank_corr(x, y, controls):
    """Spearman partial correlation: Pearson correlation of rank residuals."""
    rc = [ranks(c) for c in controls]
    return pearson(residuals(rc, ranks(x)), residuals(rc, ranks(y)))


def features(rows):
    """Department-level variables; every control is known before the 2026 results."""
    level = [r['baseline'] / r['weightTotal'] for r in rows]
    by_school = {}
    for r, lv in zip(rows, level):
        by_school.setdefault(r['school'], []).append(lv)
    return {
        'D': [(r['actual'] - r['baseline']) / r['weightTotal'] for r in rows],
        'S': [(r['v3'] - r['baseline']) / r['weightTotal'] for r in rows],
        'popularity': [math.log((r['applicant_count'] + 1) / r['official_quota']) for r in rows],
        'level': level,
        'level_sq': [(lv - 40.0) ** 2 for lv in level],
        'school_gap': [statistics.fmean(by_school[r['school']]) - lv for r, lv in zip(rows, level)],
        'rules_changed': [0.0 if r['unchangedWeights'] else 1.0 for r in rows],
    }


CONTROLS = ('popularity', 'level', 'level_sq', 'school_gap', 'rules_changed')


def encompassing(rows):
    f = features(rows)
    ctrl = [f[c] for c in CONTROLS]
    b_s, r2_s = ols([f['S']], f['D'])
    b_c, r2_c = ols(ctrl, f['D'])
    b_f, r2_f = ols([f['S']] + ctrl, f['D'])
    return {
        'n': len(rows),
        'r2_S_only': r2_s, 'slope_S_only': b_s[1],
        'r2_controls_only': r2_c,
        'r2_S_and_controls': r2_f, 'delta_r2_from_S': r2_f - r2_c,
        'coef_S_with_controls': b_f[1],
        'coef_controls_with_S': dict(zip(CONTROLS, b_f[2:])),
        'partial_spearman_D_S_given_controls': partial_rank_corr(f['D'], f['S'], ctrl),
        'partial_spearman_D_S_given_popularity': partial_rank_corr(f['D'], f['S'], [f['popularity']]),
    }


def main():
    rows = load_rows()
    j2 = common_rows(rows, ('v3', 'baseline'))
    if any(r['official_quota'] <= 0 for r in j2):
        raise ValueError('department without official quota in J2')
    out = {'note': 'exploratory; computed after the results were known; not in the dated analysis plans',
           'n_J2': len(j2), 'delta': DELTA, 'controls': list(CONTROLS)}

    # 1. Weight robustness.
    base_mae = statistics.fmean(abs(r['baseline'] - r['actual']) / r['weightTotal'] for r in j2)
    out['lambda_robustness'] = {}
    for lam in (0.3, 0.5):
        p, c = mix_difference(j2, lam)
        out['lambda_robustness'][str(lam)] = {'difference': p, 'interval': c, 'relative': p / base_mae}

    # 2. Popularity index as a rival signal.
    f = features(j2)
    hot = [d >= DELTA for d in f['D']]
    cold = [d <= -DELTA for d in f['D']]
    out['signals'] = {}
    for name in ('S', 'popularity'):
        sig = f[name]
        out['signals'][name] = {
            'spearman_with_D': spearman(f['D'], sig),
            'auroc_hot': auroc([s for s, h in zip(sig, hot) if h], [s for s, h in zip(sig, hot) if not h]),
            'auroc_cold': auroc([-s for s, c in zip(sig, cold) if c], [-s for s, c in zip(sig, cold) if not c]),
        }

    # 3. Encompassing regressions with school-cluster intervals. One resampling pass with the
    #    same seed and scheme as demand_signal.cluster_ci, so the draws match the other intervals.
    enc = encompassing(j2)
    keys = ('delta_r2_from_S', 'coef_S_with_controls', 'partial_spearman_D_S_given_controls',
            'partial_spearman_D_S_given_popularity', 'r2_controls_only', 'r2_S_only')
    groups = {}
    for r in j2:
        groups.setdefault(r['school'], []).append(r)
    schools = list(groups)
    rng = random.Random(SEED)
    draws = {k: [] for k in keys}
    for _ in range(REPETITIONS):
        sample = []
        for _ in schools:
            sample.extend(groups[schools[rng.randrange(len(schools))]])
        res = encompassing(sample)
        for k in keys:
            draws[k].append(res[k])
    for k in keys:
        v = sorted(draws[k])
        enc['interval_' + k] = [v[int(.025 * len(v))], v[int(.975 * len(v))]]
    enc['resamples'] = REPETITIONS
    out['encompassing'] = enc

    # 4. Magnitude of simulated departures among flagged departments.
    flagged_hot = [k for k, s in enumerate(f['S']) if s >= DELTA]
    flagged_cold = [k for k, s in enumerate(f['S']) if s <= -DELTA]
    out['magnitude'] = {
        'hot_flags': len(flagged_hot),
        'hot_mean_S': statistics.fmean(f['S'][k] for k in flagged_hot),
        'hot_mean_D': statistics.fmean(f['D'][k] for k in flagged_hot),
        'cold_flags': len(flagged_cold),
        'cold_mean_S': statistics.fmean(f['S'][k] for k in flagged_cold),
        'cold_mean_D': statistics.fmean(f['D'][k] for k in flagged_cold),
    }

    # 5. Direction agreement when the departure is computed from earlier simulators.
    out['other_simulators'] = {}
    for sim in ('v2', 'fractional'):
        sub = common_rows(rows, (sim, 'baseline'))
        its = [(r['school'], (r['actual'] - r['baseline']) / r['weightTotal'],
                (r[sim] - r['baseline']) / r['weightTotal'], r) for r in sub]
        det = detection(its, DELTA)
        out['other_simulators'][sim] = {'n': len(sub), 'flagged': det['flagged'],
                                        'direction_agreement': det['direction_agreement'],
                                        'spearman': det['spearman'],
                                        'auroc_hot': det['auroc_hot'], 'auroc_cold': det['auroc_cold']}

    # 6. Interpolation versus a constant shift of Fractional (shift fitted post hoc on 2026).
    err_f = [(r['fractional'] - r['actual']) / r['weightTotal'] for r in j2]
    shift = statistics.median(err_f)
    out['interpolation_vs_shift'] = {
        'n': len(j2),
        'mae_fractional': statistics.fmean(abs(e) for e in err_f),
        'best_constant_shift': shift,
        'mae_fractional_shifted': statistics.fmean(abs(e - shift) for e in err_f),
        'mae_v3': statistics.fmean(abs(r['v3'] - r['actual']) / r['weightTotal'] for r in j2),
    }

    # 7. Departments the simulation leaves underfilled.
    under = [r for r in j2 if r['quota_status'] == 'underfilled']
    out['underfilled'] = {
        'n': len(under),
        'mae_v3': statistics.fmean(abs(r['v3'] - r['actual']) / r['weightTotal'] for r in under),
        'mae_baseline': statistics.fmean(abs(r['baseline'] - r['actual']) / r['weightTotal'] for r in under),
        'bias_v3': statistics.fmean((r['v3'] - r['actual']) / r['weightTotal'] for r in under),
    }

    # 8. Departments of J2 with unchanged subjects and multipliers.
    unchanged = [r for r in j2 if r['unchangedWeights']]
    out['unchanged_rules_J2'] = {
        'n': len(unchanged),
        'mae_v3': statistics.fmean(abs(r['v3'] - r['actual']) / r['weightTotal'] for r in unchanged),
        'mae_baseline': statistics.fmean(abs(r['baseline'] - r['actual']) / r['weightTotal'] for r in unchanged),
    }

    # 9. History-missing departments: v3 against an institution-mean fallback built from history.
    #    The fallback predicts a department's level as the mean baseline level of the other
    #    departments of its institution that have a baseline, scaled by its own multiplier total.
    level_by_school = {}
    for r in j2:
        level_by_school.setdefault(r['school'], []).append(r['baseline'] / r['weightTotal'])
    missing = [r for r in common_rows(rows, ('v3',)) if r['no_history_in_snapshot']]
    paired = [r for r in missing if r['school'] in level_by_school]
    fallback = [statistics.fmean(level_by_school[r['school']]) * r['weightTotal'] for r in paired]
    out['history_missing_vs_school_mean'] = {
        'n_with_v3': len(missing),
        'n_with_school_mean': len(paired),
        'mae_v3': statistics.fmean(abs(r['v3'] - r['actual']) / r['weightTotal'] for r in paired),
        'mae_school_mean': statistics.fmean(abs(f_ - r['actual']) / r['weightTotal'] for r, f_ in zip(paired, fallback)),
    }

    output_path('exploratory-checks.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
