"""Department-level prediction intervals and event probabilities from released data (exploratory).

Split-conformal intervals for the combination's error, calibrated leaving one institution out:
the logarithm of the absolute standardized error is modeled by least squares on log listings, the
historical level and its square; the 80% (or 90%) quantile of errors divided by this scale, among the
other institutions, sets each held-out department's half-width. Fixed-width intervals use the plain
quantile. Coverage and width are reported by listings, by historical level and by platform label.
A second check fits the same scale model to the baseline method's 2025 backtest errors (level
only, since 2025 listings do not exist) and applies it to the baseline's 2026 errors, a test of
whether interval widths transfer across years. (Both added after the second simulated review.)

Added after the third simulated review: equal-tailed intervals from the signed standardized errors;
a scale model that also uses the size of the simulated departure, log(|S| + 0.5); calibration
within listing strata (Mondrian); one-sided misses; coverage by institution against what
independent departments would give; and probabilities that the official cutoff departs from the
historical baseline by at least one grade, from the same leave-one-institution-out error
distributions for the combination and for the baseline alone, scored by the Brier score against
the other institutions' base rate. Writes interval-checks.json.
"""
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import load_rows, common_rows, output_path  # noqa: E402
from exploratory_checks import ols  # noqa: E402
from history_checks import load_history  # noqa: E402

LAMBDA = 0.4
LEVEL = 0.80
BINS = ((0, 20), (20, 40), (40, 80), (80, 160), (160, 10 ** 9))
LEVEL_BINS = ((0, 30), (30, 40), (40, 45), (45, 50), (50, 61))


def conformal_quantile(scores, level=LEVEL):
    ordered = sorted(scores)
    k = min(len(ordered) - 1, math.ceil((len(ordered) + 1) * level) - 1)
    return ordered[k]


def lower_quantile(scores, level):
    ordered = sorted(scores)
    k = max(0, math.floor((len(ordered) + 1) * level) - 1)
    return ordered[k]


def scale_fit(features, target):
    """Log-linear scale model: log(|error| + 0.05) regressed on the features; returns exp(fit)."""
    beta, _ = ols([[x[k] for x in features] for k in range(len(features[0]))], [math.log(t + 0.05) for t in target])
    return lambda x: math.exp(beta[0] + sum(b * v for b, v in zip(beta[1:], x)))


def bin_label(count):
    for lo, hi in BINS:
        if lo <= count < hi:
            return f'{lo}+' if hi > 10 ** 8 else f'{lo}-{hi - 1}'


def binomial_tail_below(n, p, threshold):
    """P(X / n < threshold) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, x) * p ** x * (1 - p) ** (n - x) for x in range(n + 1) if x / n < threshold)


def summarize(results, rows_by_school):
    """results: list of (row, lower, upper) bounds on the standardized error err = (prediction - actual) / B."""
    covered = lambda r, lo, hi: lo <= r['err'] <= hi
    summary = {'coverage': statistics.fmean(covered(*t) for t in results),
               'median_width': statistics.median(hi - lo for _, lo, hi in results),
               'official_above_interval': statistics.fmean(r['err'] < lo for r, lo, _ in results),
               'official_below_interval': statistics.fmean(r['err'] > hi for r, _, hi in results),
               'bins': {}, 'level_bins': {}, 'label': {}, 'abs_S': {}}
    groups = [('bins', bin_label(lo), lambda r, lo=lo, hi=hi: lo <= r['applicant_count'] < hi) for lo, hi in BINS]
    groups += [('level_bins', f'{lo}-{min(hi, 60)}', lambda r, lo=lo, hi=hi: lo <= r['level'] < hi) for lo, hi in LEVEL_BINS]
    groups += [('label', lab, lambda r, lab=lab: r['confidence'] == lab) for lab in ('normal', 'insufficient')]
    groups += [('abs_S', '4+', lambda r: abs(r['S']) >= 4), ('abs_S', 'below 4', lambda r: abs(r['S']) < 4)]
    for key, label, keep in groups:
        sub = [t for t in results if keep(t[0])]
        summary[key][label] = {'n': len(sub), 'coverage': statistics.fmean(covered(*t) for t in sub),
                               'median_width': statistics.median(hi - lo for _, lo, hi in sub),
                               'official_above_interval': statistics.fmean(t[0]['err'] < t[1] for t in sub)}
    by_school = {}
    for t in results:
        by_school.setdefault(t[0]['school'], []).append(covered(*t))
    eligible = {k: v for k, v in by_school.items() if len(v) >= 5}
    summary['institutions'] = {
        'with_at_least_5_departments': len(eligible),
        'coverage_below_70_percent': sum(statistics.fmean(v) < 0.7 for v in eligible.values()),
        'expected_if_departments_independent': sum(binomial_tail_below(len(v), LEVEL, 0.7) for v in eligible.values())}
    return summary


def intervals(j2, level, variant):
    """Leave-one-institution-out intervals; variant in {fixed, scaled, scaled_equal_tailed, scaled_with_S,
    scaled_with_S_equal_tailed, mondrian}."""
    out = []
    feats = (lambda r: r['xs']) if 'with_S' in variant else (lambda r: r['x'])
    for school in sorted({r['school'] for r in j2}):
        train = [r for r in j2 if r['school'] != school]
        test = [r for r in j2 if r['school'] == school]
        if variant == 'fixed':
            q = conformal_quantile([abs(r['err']) for r in train], level)
            out.extend((r, -q, q) for r in test)
            continue
        sigma = scale_fit([feats(r) for r in train], [abs(r['err']) for r in train])
        if variant == 'mondrian':
            for r in test:
                same = [t for t in train if bin_label(t['applicant_count']) == bin_label(r['applicant_count'])]
                q = conformal_quantile([abs(t['err']) / sigma(feats(t)) for t in same], level)
                out.append((r, -q * sigma(feats(r)), q * sigma(feats(r))))
        elif variant.endswith('equal_tailed'):
            z = [t['err'] / sigma(feats(t)) for t in train]
            lo, hi = lower_quantile(z, (1 - level) / 2), conformal_quantile(z, (1 + level) / 2)
            out.extend((r, lo * sigma(feats(r)), hi * sigma(feats(r))) for r in test)
        else:
            q = conformal_quantile([abs(t['err']) / sigma(feats(t)) for t in train], level)
            out.extend((r, -q * sigma(feats(r)), q * sigma(feats(r))) for r in test)
    return out


def ecdf(values):
    ordered = sorted(values)
    n = len(ordered)

    def f(x):
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi) // 2
            if ordered[mid] <= x:
                lo = mid + 1
            else:
                hi = mid
        return lo / n
    return f


def event_probabilities(j2, delta=1.0):
    """P(D >= delta) and P(D <= -delta) for the combination and for the baseline alone; Brier skill."""
    probs = []
    for school in sorted({r['school'] for r in j2}):
        train = [r for r in j2 if r['school'] != school]
        test = [r for r in j2 if r['school'] == school]
        sig_c = scale_fit([r['x'] for r in train], [abs(r['err']) for r in train])
        sig_h = scale_fit([r['x'] for r in train], [abs(r['err_h']) for r in train])
        f_c = ecdf([r['err'] / sig_c(r['x']) for r in train])
        f_h = ecdf([r['err_h'] / sig_h(r['x']) for r in train])
        clim_up = statistics.fmean(r['D'] >= delta for r in train)
        clim_down = statistics.fmean(r['D'] <= -delta for r in train)
        for r in test:
            # D = 0.4 S - err for the combination and D = -err_h for the baseline.
            up_c = f_c((LAMBDA * r['S'] - delta) / sig_c(r['x']))
            down_c = 1 - f_c((LAMBDA * r['S'] + delta) / sig_c(r['x']) - 1e-12)
            up_h = f_h(-delta / sig_h(r['x']))
            down_h = 1 - f_h(delta / sig_h(r['x']) - 1e-12)
            probs.append((r, up_c, down_c, up_h, down_h, clim_up, clim_down))
    out = {}
    for side, idx_c, idx_h, idx_k, event in (('upward', 1, 3, 5, lambda r: r['D'] >= delta),
                                             ('downward', 2, 4, 6, lambda r: r['D'] <= -delta)):
        bs = lambda k: statistics.fmean((p[k] - event(p[0])) ** 2 for p in probs)
        clim, comb, hist = bs(idx_k), bs(idx_c), bs(idx_h)
        out[side] = {'base_rate': statistics.fmean(event(p[0]) for p in probs), 'brier_climatology': clim,
                     'brier_historical': hist, 'brier_combination': comb,
                     'skill_historical_vs_climatology': 1 - hist / clim,
                     'skill_combination_vs_climatology': 1 - comb / clim,
                     'skill_combination_vs_historical': 1 - comb / hist}
    return out


def main():
    rows = load_rows()
    j2 = common_rows(rows, ('v3', 'baseline'))
    for r in j2:
        r['err'] = (LAMBDA * r['v3'] + (1 - LAMBDA) * r['baseline'] - r['actual']) / r['weightTotal']
        r['err_h'] = (r['baseline'] - r['actual']) / r['weightTotal']
        r['S'] = (r['v3'] - r['baseline']) / r['weightTotal']
        r['D'] = (r['actual'] - r['baseline']) / r['weightTotal']
        level = r['baseline'] / r['weightTotal']
        r['level'] = level
        r['x'] = [math.log(r['applicant_count'] + 1), level, (level - 40) ** 2]
        r['xs'] = r['x'] + [math.log(abs(r['S']) + 0.5)]
    out = {'note': 'exploratory; added after the second and third rounds of simulated pre-submission reviews',
           'level': LEVEL, 'n': len(j2)}
    for suffix, level in (('', 0.80), ('_90', 0.90)):
        for variant in ('fixed', 'scaled'):
            out[variant + suffix] = summarize(intervals(j2, level, variant), None)
    for variant in ('scaled_equal_tailed', 'scaled_with_S', 'scaled_with_S_equal_tailed', 'mondrian'):
        out[variant] = summarize(intervals(j2, LEVEL, variant), None)
    out['event_probabilities_delta_1'] = event_probabilities(j2)

    # Cross-year transfer of the baseline component's interval widths.
    hist = load_history()
    back = []
    for r in rows:
        h = hist[r['gid']]
        if h['b25'] is not None and h['cutoff_2025'] and h['weight_total_2025']:
            level = h['b25'] / h['weight_total_2025']
            back.append(([level, (level - 40) ** 2], (h['b25'] - h['cutoff_2025']) / h['weight_total_2025']))
    sigma = scale_fit([x for x, _ in back], [abs(e) for _, e in back])
    q = conformal_quantile([abs(e) / sigma(x) for x, e in back])
    errs = [((r['baseline'] - r['actual']) / r['weightTotal'], [r['x'][1], r['x'][2]]) for r in j2]
    bias = statistics.fmean(e for e, _ in errs)
    out['baseline_cross_year'] = {
        'fitted_on': '2025 backtest of the baseline method', 'n_fit': len(back), 'n_test': len(errs),
        'coverage_2026': statistics.fmean(abs(e) <= q * sigma(x) for e, x in errs),
        'coverage_2026_after_removing_2026_mean_bias': statistics.fmean(abs(e - bias) <= q * sigma(x) for e, x in errs),
        'mean_bias_2026': bias}
    output_path('interval-checks.json').write_text(json.dumps(out, indent=2) + '\n')
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
