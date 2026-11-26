"""Checks added after a second round of simulated pre-submission reviews (exploratory).

Reads the released department file, data/history-2024.csv and data/baseline-inputs.json, and
writes robustness-checks.json:
  1. The combination's gain by type of rule change (none, multipliers only, subjects), and in
     departments whose rules did not change and whose quota changed by at most 5% or not at all.
  2. The gain across the combination weights supported by the earlier backtests.
  3. A reference for direction agreement: S permuted within deciles of the historical level.
  4. Encompassing regressions of D on S, with institution-clustered errors and with
     institution fixed effects.
  5. The share of cov(S, D) that shared transitory error can explain when only the variance
     of transitory shocks is assumed stable across years (an identified set), and direction
     agreement where S points toward continuing, rather than reversing, the 2025 change, with a
     Gaussian no-information benchmark.
  6. An ex-ante rival fitted on the 2024->2025 backtest of the baseline method and applied to
     2026, alone and combined with v3; and the leave-one-institution-out rival of Table 11
     against a combination given the same estimated 2026 intercept.
  7. The baseline's 2025 backtest bias in departments whose rules changed between 2024 and 2025.
"""
import json
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, SEED, load_rows, common_rows, output_path  # noqa: E402
from demand_signal import spearman  # noqa: E402
from exploratory_checks import ols  # noqa: E402
from history_checks import (WITH_POPULARITY, cluster_interval, cross_fit, diff_with_interval, err,  # noqa: E402
                            load_history, mae, mean_diff)

LAMBDA = 0.4
DELTA = 1.0
PERMUTATIONS = 2000
DRAWS = 200_000


def rule_change(dept):
    prior = dept.get('prior')
    if not prior or not prior.get('items'):
        return None
    now = {(i['subject'], i['weight']) for i in dept['items']}
    before = {(i['subject'], i['weight']) for i in prior['items']}
    if now == before:
        return 'unchanged'
    if {s for s, _ in now} == {s for s, _ in before}:
        return 'multipliers'
    return 'subjects'


def departures(rows):
    for r in rows:
        r['D'] = (r['actual'] - r['baseline']) / r['weightTotal']
        r['S'] = (r['v3'] - r['baseline']) / r['weightTotal']
        r['mix'] = LAMBDA * r['v3'] + (1 - LAMBDA) * r['baseline']


def agreement(rows, s_key='S'):
    flagged = [r for r in rows if abs(r[s_key]) >= DELTA and r['D'] != 0]
    if not flagged:
        return None, 0
    return sum((r[s_key] > 0) == (r['D'] > 0) for r in flagged) / len(flagged), len(flagged)


def gain_summary(rows, total_gain_sum=None):
    out = {'n': len(rows), 'mae_baseline': mae(rows, 'baseline'), 'mae_v3': mae(rows, 'v3'), 'mae_mix': mae(rows, 'mix'),
           'mix_minus_baseline': diff_with_interval(rows, 'mix', 'baseline'),
           'direction_agreement': agreement(rows)[0], 'flagged': agreement(rows)[1],
           'spearman_S_D': spearman([r['S'] for r in rows], [r['D'] for r in rows])}
    if total_gain_sum:
        out['share_of_total_gain'] = mean_diff(rows, 'mix', 'baseline') * len(rows) / total_gain_sum
    return out


def clustered_slope(rows, x_key, y_key, fixed_effects=False):
    """Slope of y on x with an intercept (or institution fixed effects) and CR1 clustered errors."""
    if fixed_effects:
        groups = {}
        for r in rows:
            groups.setdefault(r['school'], []).append(r)
        mx = {g: statistics.fmean(r[x_key] for r in m) for g, m in groups.items()}
        my = {g: statistics.fmean(r[y_key] for r in m) for g, m in groups.items()}
        x = [r[x_key] - mx[r['school']] for r in rows]
        y = [r[y_key] - my[r['school']] for r in rows]
    else:
        x0, y0 = statistics.fmean(r[x_key] for r in rows), statistics.fmean(r[y_key] for r in rows)
        x = [r[x_key] - x0 for r in rows]
        y = [r[y_key] - y0 for r in rows]
    sxx = sum(v * v for v in x)
    b = sum(a * c for a, c in zip(x, y)) / sxx
    u = [c - b * a for a, c in zip(x, y)]
    scores = {}
    for r, a, e in zip(rows, x, u):
        scores[r['school']] = scores.get(r['school'], 0.0) + a * e
    g = len(scores)
    se = math.sqrt(g / (g - 1) * sum(s * s for s in scores.values())) / sxx
    return {'slope': b, 'se': se, 't': b / se, 'clusters': g, 'n': len(rows)}


def permutation_reference(rows, seed=SEED):
    deciles = {}
    order = sorted(rows, key=lambda r: r['baseline'] / r['weightTotal'])
    for k, r in enumerate(order):
        deciles.setdefault(10 * k // len(order), []).append(r)
    rng = random.Random(seed)
    values = []
    for _ in range(PERMUTATIONS):
        for members in deciles.values():
            s = [r['S'] for r in members]
            rng.shuffle(s)
            for r, v in zip(members, s):
                r['S_perm'] = v
        values.append(agreement(rows, 'S_perm')[0])
    values.sort()
    return {'permutations': PERMUTATIONS, 'mean': statistics.fmean(values),
            'interval': [values[int(.025 * len(values))], values[int(.975 * len(values))]]}


def transitory_identified_set(rows):
    """Stationary transitory variance s2 only: var(D) = v26 + 2 s2, var(R) = v25 + 2 s2,
    cov(D, R) = s2 - c with |c| <= sqrt(v25 v26). Returns the admissible range of s2 / cov(S, D)."""
    d, r_, s = [r['D'] for r in rows], [r['R'] for r in rows], [r['S'] for r in rows]
    vd, vr = statistics.variance(d), statistics.variance(r_)
    cdr, csd = statistics.covariance(d, r_), statistics.covariance(s, d)
    grid = [k / 20000 * min(vd, vr) / 2 for k in range(20001)]
    ok = [s2 for s2 in grid if abs(s2 - cdr) <= math.sqrt(max((vd - 2 * s2) * (vr - 2 * s2), 0.0))]
    return {'n': len(rows), 'var_D': vd, 'var_R': vr, 'cov_D_R': cdr, 'cov_S_D': csd, 'var_S': statistics.variance(s),
            's2_range': [min(ok), max(ok)], 'share_range': [min(ok) / csd, max(ok) / csd],
            'share_if_persistent_changes_uncorrelated': cdr / csd}


def no_information_benchmark(moments, s2, rng):
    """Gaussian model with transitory variance s2 and S = eta - e25 (no current-year information).
    Returns direction agreement among flagged departments where S points against R."""
    vd, vr, cdr, vs = moments['var_D'], moments['var_R'], moments['cov_D_R'], moments['var_S']
    v26, v25, c = vd - 2 * s2, vr - 2 * s2, s2 - cdr
    sd = math.sqrt(s2)
    agree = total = 0
    for _ in range(DRAWS):
        z1, z2 = rng.gauss(0, 1), rng.gauss(0, 1)
        dm25 = math.sqrt(v25) * z1
        dm26 = (c / math.sqrt(v25)) * z1 + math.sqrt(max(v26 - c * c / v25, 0.0)) * z2 if v25 > 0 else math.sqrt(v26) * z2
        e24, e25, e26 = rng.gauss(0, sd), rng.gauss(0, sd), rng.gauss(0, sd)
        d = dm26 + e26 - e25
        r_ = -dm25 + e24 - e25
        s = rng.gauss(0, math.sqrt(max(vs - s2, 1e-9))) - e25
        if abs(s) >= DELTA and (s > 0) != (r_ > 0):
            total += 1
            agree += (s > 0) == (d > 0)
    return agree / total


def continuation(rows, moments):
    with_r = [r for r in rows if r['R'] != 0]
    out = {}
    for name, keep in (('reversal', lambda r: (r['S'] > 0) == (r['R'] > 0)),
                       ('continuation', lambda r: (r['S'] > 0) != (r['R'] > 0))):
        a, n = agreement([r for r in with_r if keep(r)])
        out[name] = {'direction_agreement': a, 'flagged': n}
    rng = random.Random(SEED)
    lo, hi = moments['s2_range']
    grid = [lo + (hi - lo) * k / 4 for k in range(5)]
    sims = {f'{s2:.3f}': no_information_benchmark(moments, s2, rng) for s2 in grid if s2 > 0}
    out['no_information_benchmark'] = {'draws': DRAWS, 'by_s2': sims, 'max': max(sims.values())}
    return out


def ex_ante_rival(j2, history, schools):
    """Fit D on history, rule and quota variables in the 2024->2025 backtest; apply to 2026."""
    train = []
    for gid, h in history.items():
        if h['b25'] is None or not h['cutoff_2025'] or not h['weight_total_2025'] or not h['quota_2024'] or not h['quota_2025']:
            continue
        train.append({'gid': gid, 'school': schools[gid], 'level': h['b25'] / h['weight_total_2025'],
                      'D': (h['cutoff_2025'] - h['b25']) / h['weight_total_2025'],
                      'rules': 1.0 if h['rules_changed'] else 0.0, 'dq': math.log(h['quota_2025'] / h['quota_2024'])})

    def design(rows):
        by_school = {}
        for r in rows:
            by_school.setdefault(r['school'], []).append(r['level'])
        return [[r['level'] for r in rows], [(r['level'] - 40) ** 2 for r in rows],
                [statistics.fmean(by_school[r['school']]) - r['level'] for r in rows],
                [r['rules'] for r in rows], [r['dq'] for r in rows]]

    beta, r2 = ols(design(train), [r['D'] for r in train])
    test = [{'school': r['school'], 'level': r['baseline'] / r['weightTotal'],
             'rules': 0.0 if r['unchangedWeights'] else 1.0,
             'dq': math.log(r['official_quota'] / r['quota_2025']) if r.get('quota_2025') else 0.0} for r in j2]
    cols = design(test)
    slopes = [sum(b * col[i] for b, col in zip(beta[1:], cols)) for i in range(len(j2))]
    centre = statistics.fmean(slopes)
    for r, sl in zip(j2, slopes):
        r['rival_intercept'] = r['baseline'] + r['weightTotal'] * (beta[0] + sl)
        r['rival'] = r['baseline'] + r['weightTotal'] * (sl - centre)
        r['rival_mix'] = LAMBDA * r['v3'] + (1 - LAMBDA) * r['rival']
        r['rival_intercept_mix'] = LAMBDA * r['v3'] + (1 - LAMBDA) * r['rival_intercept']
    return {'n_train': len(train), 'r2_train': r2,
            'coefficients': dict(zip(('intercept', 'level', 'level_sq', 'school_gap', 'rules_changed', 'quota_change'), beta)),
            'n': len(j2),
            'mae': {k: mae(j2, k) for k in ('baseline', 'rival', 'rival_intercept', 'mix', 'rival_mix', 'rival_intercept_mix')},
            'rival_minus_baseline': diff_with_interval(j2, 'rival', 'baseline'),
            'rival_mix_minus_rival': diff_with_interval(j2, 'rival_mix', 'rival'),
            'rival_intercept_mix_minus_rival_intercept': diff_with_interval(j2, 'rival_intercept_mix', 'rival_intercept')}


def loio_intercept(j2):
    """Table 11's leave-one-institution-out rival against the combination given the same kind of
    2026 intercept, estimated from the other institutions."""
    preds = cross_fit(j2, WITH_POPULARITY)
    for r, p in zip(j2, preds):
        r['loio_rival'] = p
    for school in {r['school'] for r in j2}:
        a = statistics.fmean((r['actual'] - r['mix']) / r['weightTotal'] for r in j2 if r['school'] != school)
        b = statistics.fmean((r['actual'] - r['baseline']) / r['weightTotal'] for r in j2 if r['school'] != school)
        for r in j2:
            if r['school'] == school:
                r['mix_intercept'] = r['mix'] + r['weightTotal'] * a
                r['baseline_intercept'] = r['baseline'] + r['weightTotal'] * b
    # The baseline with the same kind of intercept was added after the third simulated review.
    return {'mae_loio_rival': mae(j2, 'loio_rival'), 'mae_mix_with_intercept': mae(j2, 'mix_intercept'),
            'mae_baseline_with_intercept': mae(j2, 'baseline_intercept'),
            'mix_with_intercept_minus_loio_rival': diff_with_interval(j2, 'mix_intercept', 'loio_rival'),
            'mix_with_intercept_minus_baseline_with_intercept': diff_with_interval(j2, 'mix_intercept', 'baseline_intercept')}


def main():
    rows = load_rows()
    history = load_history()
    import csv
    with (PAPER / 'data/history-2024.csv').open(newline='') as fh:
        changed = {int(r['gid']): r['rules_changed_2024_2025'] == 'True' for r in csv.DictReader(fh)}
    for gid, h in history.items():
        h['rules_changed'] = changed.get(gid, False)
    inputs = {d['gid']: d for d in json.loads((PAPER / 'data/baseline-inputs.json').read_text())['departments']}
    schools = {r['gid']: r['school'] for r in rows}
    for r in rows:
        r.update(history[r['gid']])
        r['rule_change'] = rule_change(inputs[r['gid']]) if r['gid'] in inputs else None
    j2 = common_rows(rows, ('v3', 'baseline'))
    departures(j2)
    total = mean_diff(j2, 'mix', 'baseline') * len(j2)
    out = {'note': 'exploratory; added after a second round of simulated pre-submission reviews', 'n_J2': len(j2),
           'all': gain_summary(j2)}

    # 1. Rule and quota structure.
    out['rule_change'] = {name: gain_summary([r for r in j2 if r['rule_change'] == name], total)
                          for name in ('unchanged', 'multipliers', 'subjects')}
    out['rule_change']['unchangedWeights_flag_agrees'] = sum(
        (r['rule_change'] == 'unchanged') == r['unchangedWeights'] for r in j2)
    stable = [r for r in j2 if r['unchangedWeights'] and r['quota_2025']]
    out['structure_unchanged'] = {
        'quota_within_5pct': gain_summary([r for r in stable if abs(math.log(r['official_quota'] / r['quota_2025'])) <= math.log(1.05)]),
        'quota_identical': gain_summary([r for r in stable if r['official_quota'] == r['quota_2025']])}

    # 2. Weights supported by the backtests.
    out['lambda'] = {}
    for lam in (0.106, 0.2, 0.3, 0.346, 0.393, 0.4, 0.44, 0.5):
        m = statistics.fmean(abs(lam * err(r, 'v3') + (1 - lam) * err(r, 'baseline')) for r in j2)
        out['lambda'][f'{lam:.3f}'] = {'mae': m, 'relative_to_baseline': m / mae(j2, 'baseline') - 1}

    # 3. Reference for direction agreement.
    out['direction_agreement'] = {'observed': agreement(j2)[0], 'flagged': agreement(j2)[1],
                                  'permuted_within_level_deciles': permutation_reference(j2)}

    # 4. Encompassing regressions.
    out['encompassing'] = {'D_on_S': clustered_slope(j2, 'S', 'D'),
                           'D_on_S_institution_fixed_effects': clustered_slope(j2, 'S', 'D', fixed_effects=True)}

    # 5. Transitory error: identified set and continuation versus reversal.
    j2h = [r for r in j2 if r['h24'] is not None]
    for r in j2h:
        r['R'] = (r['h24'] - r['baseline']) / r['weightTotal']
    moments = transitory_identified_set(j2h)
    both = [r for r in j2h if r['b25'] is not None and r['cutoff_2025'] and r['weight_total_2025']]
    moments['corr_R_with_2025_backtest_error'] = statistics.correlation(
        [r['R'] for r in both], [(r['b25'] - r['cutoff_2025']) / r['weight_total_2025'] for r in both])
    moments['corr_R_error_with_baseline_error'] = statistics.correlation(
        [err(r, 'h24') for r in j2h], [err(r, 'baseline') for r in j2h])
    out['transitory'] = moments
    out['continuation'] = continuation(j2h, moments)

    # 6. Rivals.
    out['ex_ante_rival'] = ex_ante_rival(j2, history, schools)
    out['loio_rival_with_common_intercept'] = loio_intercept(j2)

    # 7. The baseline's 2025 backtest bias by rule change between 2024 and 2025.
    back = [h for h in history.values() if h['b25'] is not None and h['cutoff_2025'] and h['weight_total_2025']]
    bias = lambda hs: statistics.fmean((h['b25'] - h['cutoff_2025']) / h['weight_total_2025'] for h in hs)
    out['backtest_2025'] = {'n': len(back), 'bias': bias(back),
                            'rules_changed': {'n': sum(h['rules_changed'] for h in back),
                                              'bias': bias([h for h in back if h['rules_changed']])},
                            'rules_unchanged': {'n': sum(not h['rules_changed'] for h in back),
                                                'bias': bias([h for h in back if not h['rules_changed']])}}
    # 8. Direct ablations and availability groups on released values (Supplement S14).
    have = lambda r, k: r.get(k) is not None
    pair = lambda a, b: [r for r in rows if have(r, a) and have(r, b)]
    out['availability'] = {
        'v2_fractional': {'n': len(pair('v2', 'fractional')), 'mae_v2': mae(pair('v2', 'fractional'), 'v2'),
                          'mae_fractional': mae(pair('v2', 'fractional'), 'fractional')},
        'fractional_v3': {'n': len(pair('fractional', 'v3')), 'mae_fractional': mae(pair('fractional', 'v3'), 'fractional'),
                          'mae_v3': mae(pair('fractional', 'v3'), 'v3')},
        'new_with_fractional': {'n': len([r for r in pair('fractional', 'v3') if not have(r, 'v2')]),
                                'mae_fractional': mae([r for r in pair('fractional', 'v3') if not have(r, 'v2')], 'fractional'),
                                'mae_v3': mae([r for r in pair('fractional', 'v3') if not have(r, 'v2')], 'v3')},
        'groups': {name: {'n': len(g), 'mae_v3': mae(g, 'v3') if g and have(g[0], 'v3') else None,
                          'mae_baseline': mae(g, 'baseline') if g and have(g[0], 'baseline') else None}
                   for name, g in (('both', [r for r in rows if have(r, 'v3') and have(r, 'baseline')]),
                                   ('v3_only', [r for r in rows if have(r, 'v3') and not have(r, 'baseline')]),
                                   ('baseline_only', [r for r in rows if not have(r, 'v3') and have(r, 'baseline')]),
                                   ('neither', [r for r in rows if not have(r, 'v3') and not have(r, 'baseline')]))}}
    for r in j2:
        for key in ('S_perm',):
            r.pop(key, None)
    output_path('robustness-checks.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
