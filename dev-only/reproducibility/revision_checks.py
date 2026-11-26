"""Checks added in the fifth revision, from released data (exploratory; added after a fourth round of simulated review).

1. tails: excess kurtosis of the errors; MAE split at two grades into the part within two grades and the excess beyond;
   the share of departments where v3 is closer than the baseline; errors of at least four grades; MAE after removing each
   method's largest 5% of absolute errors; the absolute error above which v3's exceedance curve stays above the
   baseline's; where v3's errors of at least four grades fall, and the comparison without those kinds of departments;
   the share of the MAE gap between v3 and the baseline from departments with |S| >= 8.
2. slopes: the regression of D on S by least squares, Huber's M-estimator and least absolute deviations, slopes within
   bands of |S|, and the share of the sum of S^2 from departments with |S| >= 8.
3. structure: the gain in the departments whose rules and quota did not change, with and without the department whose
   paired difference in absolute error is largest in absolute value, and without the one where the combination does
   worst, and the Hodges-Lehmann estimate of the paired difference.
4. accuracy: relative changes in RMSE and median absolute error; institutions where the combination (or v3) has lower
   MAE than the baseline, with a two-sided sign test; quota-weighted MAE; the interpolation's share of the gain; v2 at
   the weight of its own backtest (0.119).
5. decision: quantile predictions for an applicant who weighs a cutoff above the chosen threshold k times as heavily, per
   grade, as needless caution: tau = k/(1+k), k = 1, 3, 9, 19. The margin added to each point prediction is the tau
   quantile of the signed errors of the other institutions (2026) or of the baseline's 2025 backtest (ex ante). Pinball
   loss; the baseline's loss is the expected value of perfect information for this decision, so 1 - L(mix)/L(baseline)
   is the share of it the combination captures. CRPS of the predictive distributions (point prediction plus the other
   institutions' errors). Probabilities that the official cutoff exceeds the prediction by more than a margin, and the
   margin that holds that probability at 10% and 5%. The weight minimizing pinball loss for each k.
6. equity: errors, gains and risks by region (county of the campus, National Development Council regions) and level;
   two-sided risks below level 30; coverage of 80% split-conformal intervals by level, sector and region, and with
   calibration within level bands; withheld departments by sector; overlap of simulated and official underfilling; the
   simulation's bias below level 30 by its own filling status.
7. level: the combination's gain if every simulated cutoff were shifted by a fixed number of grades (for example, the
   rise that longer preference lists would bring), with and without centering the simulated departures on their mean.
8. contrasts (added after the fifth simulated review): differences in the gain between groups, with institution-cluster
   intervals computed within each resample.
Writes revision-checks.json.
"""
import bisect
import csv
import json
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, SEED as ANALYSIS_SEED, load_rows, common_rows, output_path  # noqa: E402
from history_checks import REPS, cluster_interval, load_history  # noqa: E402
from interval_checks import conformal_quantile, intervals, scale_fit  # noqa: E402
from robustness_checks import rule_change  # noqa: E402

LAMBDA = 0.4
KS = (1, 3, 9, 19)
SEED = ANALYSIS_SEED  # the institution-cluster seed of the main text
LEVEL_BANDS = ((0, 30), (30, 40), (40, 45), (45, 50), (50, 61))

# County of the campus (Ministry of Education directory), grouped into the National Development Council's regions:
# north (Taipei, New Taipei, Keelung, Taoyuan, Hsinchu, Yilan), central (Miaoli, Taichung, Changhua, Nantou, Yunlin),
# south (Chiayi, Tainan, Kaohsiung, Pingtung), east (Hualien, Taitung) and the offshore county of Kinmen.
REGION = {
    'south': ('南華大學', '國立中山大學', '國立中正大學', '國立嘉義大學', '國立屏東大學', '國立成功大學', '國立臺南大學',
              '國立臺南藝術大學', '國立高雄大學', '國立高雄師範大學', '長榮大學', '義守大學', '高雄醫學大學'),
    'east_and_kinmen': ('國立東華大學', '國立臺東大學', '慈濟大學', '國立金門大學'),
    'central': ('中國醫藥大學', '中山醫學大學', '亞洲大學', '國立中興大學', '國立彰化師範大學', '國立暨南國際大學',
                '國立聯合大學', '國立臺中教育大學', '國立臺灣體育運動大學', '大葉大學', '東海大學', '逢甲大學', '靜宜大學'),
    'north': ('世新大學', '中原大學', '中國文化大學', '佛光大學', '元智大學', '國立中央大學', '國立宜蘭大學', '國立政治大學',
              '國立清華大學', '國立臺北大學', '國立臺北教育大學', '國立臺灣大學', '國立臺灣師範大學', '國立臺灣海洋大學',
              '國立臺灣藝術大學', '國立陽明交通大學', '國立體育大學', '大同大學', '實踐大學', '康寧大學', '東吳大學',
              '淡江大學', '玄奘大學', '真理大學', '臺北市立大學', '臺北醫學大學', '輔仁大學', '銘傳大學', '長庚大學',
              '馬偕醫學大學'),
}
SCHOOL_REGION = {school: region for region, schools in REGION.items() for school in schools}


def region_of(r):
    # Two universities name a branch campus in the department name; Kang Ning's departments are at its Taipei campus.
    if r['school'] == '實踐大學' and '高雄校區' in r['department']:
        return 'south'
    return SCHOOL_REGION[r['school']]


public = lambda r: r['school'].startswith(('國立', '臺北市立', '高雄市立', '市立'))


def errors(r):
    h = (r['baseline'] - r['actual']) / r['weightTotal']
    v = (r['v3'] - r['actual']) / r['weightTotal']
    r['eH'], r['eV'], r['eM'] = h, v, LAMBDA * v + (1 - LAMBDA) * h
    r['S'] = (r['v3'] - r['baseline']) / r['weightTotal']
    r['D'] = (r['actual'] - r['baseline']) / r['weightTotal']
    r['level'] = r['baseline'] / r['weightTotal']


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def mae(rows, key):
    return mean(abs(r[key]) for r in rows)


def ci(rows, stat, reps=REPS):
    return cluster_interval(rows, stat, repetitions=reps, seed=SEED)


def gain(rows, a='eM', b='eH'):
    return mean(abs(r[a]) - abs(r[b]) for r in rows)


def excess_kurtosis(xs):
    m = mean(xs)
    m2 = mean((x - m) ** 2 for x in xs)
    m4 = mean((x - m) ** 4 for x in xs)
    return m4 / m2 ** 2 - 3


# ---------------------------------------------------------------- 1. tails

def tails(j2):
    out = {'excess_kurtosis': {k: excess_kurtosis([r[k] for r in j2]) for k in ('eH', 'eV', 'eM')}}
    bulk = lambda rows, k: mean(min(abs(r[k]), 2) for r in rows)
    over = lambda rows, k: mean(max(abs(r[k]) - 2, 0) for r in rows)
    out['split_at_two_grades'] = {
        'within': {'baseline': bulk(j2, 'eH'), 'v3': bulk(j2, 'eV'),
                   'v3_minus_baseline': bulk(j2, 'eV') - bulk(j2, 'eH'),
                   'interval': ci(j2, lambda s: bulk(s, 'eV') - bulk(s, 'eH'))},
        'beyond': {'baseline': over(j2, 'eH'), 'v3': over(j2, 'eV'),
                   'v3_minus_baseline': over(j2, 'eV') - over(j2, 'eH'),
                   'interval': ci(j2, lambda s: over(s, 'eV') - over(s, 'eH'))}}
    out['v3_closer_than_baseline'] = mean(abs(r['eV']) < abs(r['eH']) for r in j2)
    out['at_least_four_grades'] = {k: mean(abs(r[e]) >= 4 for r in j2) for k, e in (('baseline', 'eH'), ('v3', 'eV'), ('combination', 'eM'))}
    trim = lambda k: mean(sorted(abs(r[k]) for r in j2)[:len(j2) - math.ceil(0.05 * len(j2))])
    out['mae_without_own_largest_5pct'] = {'baseline': trim('eH'), 'v3': trim('eV'), 'combination': trim('eM')}
    grid = [t / 100 for t in range(0, 1001)]
    exceed = lambda k, t: mean(abs(r[k]) > t for r in j2)
    above = [exceed('eV', t) > exceed('eH', t) for t in grid]
    cross = next((grid[i] for i in range(len(grid)) if all(above[i:])), None)
    out['exceedance_crossing'] = cross
    big = [r for r in j2 if abs(r['eV']) >= 4]
    kinds = {'fewer_than_20_listings': lambda r: r['applicant_count'] < 20, 'level_below_30': lambda r: r['level'] < 30,
             'simulation_underfilled': lambda r: r['quota_status'] == 'underfilled'}
    out['large_v3_errors'] = {'n': len(big), **{k: {'among_large': mean(f(r) for r in big), 'among_all': mean(f(r) for r in j2)}
                                                 for k, f in kinds.items()}}
    rest = [r for r in j2 if not any(f(r) for f in kinds.values())]
    out['without_those_kinds'] = {'n': len(rest), 'mae_baseline': mae(rest, 'eH'), 'mae_v3': mae(rest, 'eV'),
                                  'mae_combination': mae(rest, 'eM'), 'relative_gain': mae(rest, 'eM') / mae(rest, 'eH') - 1,
                                  'gain': gain(rest), 'interval': ci(rest, gain)}
    extreme = [r for r in j2 if abs(r['S']) >= 8]
    total_gap = sum(abs(r['eV']) - abs(r['eH']) for r in j2)
    out['s_at_least_8'] = {'n': len(extreme), 'share_of_sum_S2': sum(r['S'] ** 2 for r in extreme) / sum(r['S'] ** 2 for r in j2),
                           'share_of_v3_minus_baseline_gap': sum(abs(r['eV']) - abs(r['eH']) for r in extreme) / total_gap}
    return out


# ---------------------------------------------------------------- 2. slopes

def fit_line(xs, ys, weights=None):
    w = weights or [1.0] * len(xs)
    sw = sum(w)
    mx = sum(wi * x for wi, x in zip(w, xs)) / sw
    my = sum(wi * y for wi, y in zip(w, ys)) / sw
    sxx = sum(wi * (x - mx) ** 2 for wi, x in zip(w, xs))
    sxy = sum(wi * (x - mx) * (y - my) for wi, x, y in zip(w, xs, ys))
    b = sxy / sxx
    return my - b * mx, b


def huber(xs, ys, k=1.345, iterations=50):
    a, b = fit_line(xs, ys)
    for _ in range(iterations):
        res = [y - a - b * x for x, y in zip(xs, ys)]
        scale = statistics.median(abs(e) for e in res) / 0.6745 or 1e-9
        w = [1.0 if abs(e) <= k * scale else k * scale / abs(e) for e in res]
        a, b = fit_line(xs, ys, w)
    return b


def lad(xs, ys, iterations=100):
    a, b = fit_line(xs, ys)
    for _ in range(iterations):
        w = [1 / max(abs(y - a - b * x), 1e-6) for x, y in zip(xs, ys)]
        a, b = fit_line(xs, ys, w)
    return b


def slopes(j2):
    xs, ys = [r['S'] for r in j2], [r['D'] for r in j2]
    out = {'least_squares': fit_line(xs, ys)[1], 'huber': huber(xs, ys), 'least_absolute_deviations': lad(xs, ys)}
    out['huber_interval'] = ci(j2, lambda s: huber([r['S'] for r in s], [r['D'] for r in s], iterations=15))
    out['lad_interval'] = ci(j2, lambda s: lad([r['S'] for r in s], [r['D'] for r in s], iterations=30))
    out['by_abs_S'] = {}
    for lo, hi in ((0, 2), (2, 4), (4, 8), (8, math.inf)):
        sub = [r for r in j2 if lo <= abs(r['S']) < hi]
        out['by_abs_S'][f'{lo}-{hi}'] = {'n': len(sub), 'slope': fit_line([r['S'] for r in sub], [r['D'] for r in sub])[1]}
    return out


# ---------------------------------------------------------------- 3. structure

def hodges_lehmann(d):
    walsh = [(d[i] + d[j]) / 2 for i in range(len(d)) for j in range(i, len(d))]
    return statistics.median(walsh)


def structure(j2):
    history = load_history()
    stable = [r for r in j2 if r['unchangedWeights'] and history[r['gid']]['quota_2025']
              and r['official_quota'] == history[r['gid']]['quota_2025']]
    largest = max(stable, key=lambda r: abs(abs(r['eM']) - abs(r['eH'])))
    rest = [r for r in stable if r is not largest]
    hl = lambda rows: hodges_lehmann([abs(r['eM']) - abs(r['eH']) for r in rows])
    return {'n': len(stable), 'gain': gain(stable), 'relative': mae(stable, 'eM') / mae(stable, 'eH') - 1,
            'interval': ci(stable, gain),
            'most_influential': {'paired_difference': abs(largest['eM']) - abs(largest['eH']), 'S': largest['S'],
                                 'official_quota': largest['official_quota'], 'listings': largest['applicant_count']},
            'without_it': {'n': len(rest), 'gain': gain(rest), 'relative': mae(rest, 'eM') / mae(rest, 'eH') - 1, 'interval': ci(rest, gain)},
            'without_worst': (lambda w: (lambda rest2: {'paired_difference': abs(w['eM']) - abs(w['eH']), 'S': w['S'],
                                                        'official_quota': w['official_quota'], 'n': len(rest2), 'gain': gain(rest2),
                                                        'relative': mae(rest2, 'eM') / mae(rest2, 'eH') - 1,
                                                        'interval': ci(rest2, gain)})([r for r in stable if r is not w]))(
                max(stable, key=lambda r: abs(r['eM']) - abs(r['eH']))),
            'hodges_lehmann': hl(stable), 'hodges_lehmann_interval': ci(stable, hl)}


# ---------------------------------------------------------------- 4. accuracy

def sign_test(wins, n):
    tail = sum(math.comb(n, k) for k in range(0, min(wins, n - wins) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def accuracy(rows, j2):
    rmse = lambda k: math.sqrt(mean(r[k] ** 2 for r in j2))
    med = lambda k: statistics.median(abs(r[k]) for r in j2)
    out = {'rmse_relative': rmse('eM') / rmse('eH') - 1, 'median_relative': med('eM') / med('eH') - 1}
    schools = {}
    for r in j2:
        schools.setdefault(r['school'], []).append(r)
    for key, label in (('eM', 'combination'), ('eV', 'v3')):
        wins = sum(mae(s, key) < mae(s, 'eH') for s in schools.values())
        out[f'institutions_where_{label}_beats_baseline'] = {'wins': wins, 'institutions': len(schools),
                                                             'sign_test_p': sign_test(wins, len(schools))}
    q = lambda k: sum(r['official_quota'] * abs(r[k]) for r in j2) / sum(r['official_quota'] for r in j2)
    out['quota_weighted'] = {'baseline': q('eH'), 'v3': q('eV'), 'combination': q('eM'),
                             'v3_minus_baseline': q('eV') - q('eH'), 'combination_relative': q('eM') / q('eH') - 1}
    for r in j2:
        r['eF'] = ((r['fractional'] - r['actual']) / r['weightTotal']) if r['fractional'] is not None else None
    withF = [r for r in j2 if r['eF'] is not None]
    for r in withF:
        r['eMF'] = LAMBDA * r['eF'] + (1 - LAMBDA) * r['eH']
    out['interpolation_share_of_gain'] = {
        'n': len(withF), 'gain_v3': gain(withF), 'gain_fractional': gain(withF, 'eMF'),
        'v3_minus_fractional': gain(withF, 'eM', 'eMF'), 'interval': ci(withF, lambda s: gain(s, 'eM', 'eMF')),
        'share': gain(withF, 'eM', 'eMF') / gain(withF)}
    v2 = [r for r in common_rows(rows, ('v2', 'baseline'))]
    for r in v2:
        r['eH'] = (r['baseline'] - r['actual']) / r['weightTotal']
        r['e2'] = (r['v2'] - r['actual']) / r['weightTotal']
    out['v2_weights'] = {f'{lam:.3f}': mean(abs(lam * r['e2'] + (1 - lam) * r['eH']) for r in v2) / mae(v2, 'eH') - 1
                         for lam in (0.119, 0.4)}
    out['v2_weights']['n'] = len(v2)
    return out


# ---------------------------------------------------------------- 5. decision

def pinball(u, tau):
    return tau * u if u >= 0 else (tau - 1) * u


def lower_q(values, p):
    s = sorted(values)
    return s[min(len(s) - 1, max(0, math.ceil(p * len(s)) - 1))]


def loio_margins(j2, key, tau):
    """For each department, the tau quantile of y - prediction (= -e) among other institutions' departments."""
    by_school = {}
    for r in j2:
        by_school.setdefault(r['school'], []).append(r)
    margins = {}
    for school, test in by_school.items():
        train = [-r[key] for r in j2 if r['school'] != school]
        m = lower_q(train, tau)
        for r in test:
            margins[r['gid']] = m
    return margins


class Ecdf:
    """Sorted values with prefix sums: mean |z - u| in O(log n), and the Gini mean difference."""

    def __init__(self, values):
        self.z = sorted(values)
        self.n = len(self.z)
        self.prefix = [0.0]
        for v in self.z:
            self.prefix.append(self.prefix[-1] + v)
        self.gini = 2 * sum(v * (2 * (i + 1) - self.n - 1) for i, v in enumerate(self.z)) / self.n ** 2

    def mean_abs(self, u):
        k = bisect.bisect_left(self.z, u)
        below = u * k - self.prefix[k]
        above = (self.prefix[self.n] - self.prefix[k]) - u * (self.n - k)
        return (below + above) / self.n


def crps(j2, key):
    by_school = {}
    for r in j2:
        by_school.setdefault(r['school'], []).append(r)
    out = {}
    for school, test in by_school.items():
        f = Ecdf([-r[key] for r in j2 if r['school'] != school])
        for r in test:
            out[r['gid']] = f.mean_abs(-r[key]) - f.gini / 2
    return out


def decision(j2, history):
    out = {'k': {}}
    back = [-(h['b25'] - h['cutoff_2025']) / h['weight_total_2025'] for h in history.values()
            if h['b25'] is not None and h['cutoff_2025'] and h['weight_total_2025']]
    for k in KS:
        tau = k / (1 + k)
        entry = {'tau': tau}
        for source in ('loio_2026', 'backtest_2025'):
            if source == 'loio_2026':
                mh, mm = loio_margins(j2, 'eH', tau), loio_margins(j2, 'eM', tau)
            else:
                m = lower_q(back, tau)
                mh = mm = {r['gid']: m for r in j2}
            for r in j2:
                r['_lh'] = pinball(-r['eH'] - mh[r['gid']], tau)
                r['_lm'] = pinball(-r['eM'] - mm[r['gid']], tau)
            share = lambda s: 1 - mean(r['_lm'] for r in s) / mean(r['_lh'] for r in s)
            entry[source] = {'loss_baseline': mean(r['_lh'] for r in j2), 'loss_combination': mean(r['_lm'] for r in j2),
                             'share_of_evpi_captured': share(j2), 'interval': ci(j2, share)}
            if source == 'loio_2026':
                stable = [r for r in j2 if r['unchangedWeights'] and history[r['gid']]['quota_2025']
                          and r['official_quota'] == history[r['gid']]['quota_2025']]
                entry['rules_and_quota_unchanged'] = {'n': len(stable), 'share_of_evpi_captured': share(stable),
                                                      'interval': ci(stable, share)}
        # Weight minimizing the pinball loss, each weight with its own leave-one-institution-out margins.
        best = None
        for step in range(0, 21):
            lam = step / 20
            for r in j2:
                r['_e'] = lam * r['eV'] + (1 - lam) * r['eH']
            mg = loio_margins(j2, '_e', tau)
            loss = mean(pinball(-r['_e'] - mg[r['gid']], tau) for r in j2)
            if best is None or loss < best[1]:
                best = (lam, loss)
        entry['best_weight'] = {'weight': best[0], 'loss': best[1],
                                'loss_at_0.4_relative_to_best': entry['loio_2026']['loss_combination'] / best[1] - 1}
        out['k'][str(k)] = entry
    ch, cm = crps(j2, 'eH'), crps(j2, 'eM')
    for r in j2:
        r['_ch'], r['_cm'] = ch[r['gid']], cm[r['gid']]
    skill = lambda s: 1 - mean(r['_cm'] for r in s) / mean(r['_ch'] for r in s)
    out['crps'] = {'baseline': mean(ch.values()), 'combination': mean(cm.values()), 'skill': skill(j2),
                   'interval': ci(j2, skill)}
    out['exceeds_prediction_by_more_than'] = {}
    for m in (0, 0.5, 1, 1.5, 2, 3):
        share = lambda s, key, m=m: mean(-r[key] > m for r in s)
        out['exceeds_prediction_by_more_than'][str(m)] = {
            'baseline': share(j2, 'eH'), 'combination': share(j2, 'eM'),
            'difference': share(j2, 'eM') - share(j2, 'eH'),
            'interval': ci(j2, lambda s, m=m: mean(-r['eM'] > m for r in s) - mean(-r['eH'] > m for r in s))}
    out['margin_for_risk'] = {}
    for risk in (0.10, 0.05):
        marg = lambda s, key, risk=risk: lower_q([-r[key] for r in s], 1 - risk)
        out['margin_for_risk'][f'{risk:.2f}'] = {
            'baseline': marg(j2, 'eH'), 'combination': marg(j2, 'eM'),
            'saving': marg(j2, 'eH') - marg(j2, 'eM'),
            'interval': ci(j2, lambda s, risk=risk: lower_q([-r['eH'] for r in s], 1 - risk) - lower_q([-r['eM'] for r in s], 1 - risk))}
    return out


# ---------------------------------------------------------------- 6. equity

def equity(rows, j2):
    audit = {int(r['gid']): int(r['admitted_including_extra'])
             for r in csv.DictReader((PAPER / 'data/official-rules-audit.csv').open())}
    official_under = lambda r: audit[r['gid']] < r['official_quota']
    summary = lambda s: {
        'n': len(s), 'institutions': len({r['school'] for r in s}), 'private_share': mean(not public(r) for r in s),
        'mae_baseline': mae(s, 'eH'), 'mae_v3': mae(s, 'eV'), 'mae_combination': mae(s, 'eM'),
        'bias_baseline': mean(r['eH'] for r in s), 'bias_v3': mean(r['eV'] for r in s),
        'gain': gain(s), 'relative': mae(s, 'eM') / mae(s, 'eH') - 1,
        'interval': ci(s, gain) if len({r['school'] for r in s}) >= 5 else None,
        'above_baseline': mean(r['eH'] <= -1 for r in s), 'above_combination': mean(r['eM'] <= -1 for r in s),
        'below_baseline': mean(r['eH'] >= 1 for r in s), 'below_combination': mean(r['eM'] >= 1 for r in s),
        'combination_worse_by_half_grade': mean(abs(r['eM']) - abs(r['eH']) >= 0.5 for r in s),
        'fewer_than_20_listings': mean(r['applicant_count'] < 20 for r in s)}
    out = {'regions': {}, 'region_by_level': {}}
    for region in ('north', 'central', 'south', 'east_and_kinmen'):
        sub = [r for r in j2 if r['region'] == region]
        out['regions'][region] = summary(sub)
        for label, keep in (('below_30', lambda r: r['level'] < 30), ('30_and_above', lambda r: r['level'] >= 30)):
            out['region_by_level'][f'{region}|{label}'] = summary([r for r in sub if keep(r)])
    for label, regions in (('north_and_central', ('north', 'central')), ('south_east_and_kinmen', ('south', 'east_and_kinmen'))):
        out['region_by_level'][f'{label}|below_30'] = summary([r for r in j2 if r['region'] in regions and r['level'] < 30])
    out['levels'] = {f'{lo}-{hi}': summary([r for r in j2 if lo <= r['level'] < hi]) for lo, hi in LEVEL_BANDS}
    out['levels']['0-30']['quota_share'] = (sum(r['official_quota'] for r in j2 if r['level'] < 30)
                                            / sum(r['official_quota'] for r in j2))
    out['sector'] = {'public': summary([r for r in j2 if public(r)]), 'private': summary([r for r in j2 if not public(r)])}
    # Coverage of the 80% scaled split-conformal intervals of Section 6.3, and of intervals calibrated within level bands.
    for r in j2:
        r['err'] = r['eM']
        r['x'] = [math.log(r['applicant_count'] + 1), r['level'], (r['level'] - 40) ** 2]
    scaled = intervals(j2, 0.80, 'scaled')
    band = lambda r: next(f'{lo}-{hi}' for lo, hi in LEVEL_BANDS if lo <= r['level'] < hi)
    by_level = []
    for school in sorted({r['school'] for r in j2}):
        train = [r for r in j2 if r['school'] != school]
        test = [r for r in j2 if r['school'] == school]
        sigma = scale_fit([t['x'] for t in train], [abs(t['err']) for t in train])
        for r in test:
            same = [t for t in train if band(t) == band(r)]
            q = conformal_quantile([abs(t['err']) / sigma(t['x']) for t in same], 0.80)
            by_level.append((r, -q * sigma(r['x']), q * sigma(r['x'])))
    covered = lambda items, keep: mean(lo <= r['err'] <= hi for r, lo, hi in items if keep(r))
    groups = {'all': lambda r: True, **{f'level {lo}-{hi}': (lambda r, lo=lo, hi=hi: lo <= r['level'] < hi) for lo, hi in LEVEL_BANDS},
              'public': public, 'private': lambda r: not public(r),
              **{f'region {g}': (lambda r, g=g: r['region'] == g) for g in REGION},
              'south, east and Kinmen below 30': lambda r: r['region'] in ('south', 'east_and_kinmen') and r['level'] < 30}
    out['interval_coverage'] = {name: {'scaled': covered(scaled, keep), 'calibrated_within_level': covered(by_level, keep)}
                                for name, keep in groups.items()}
    withheld = [r for r in rows if r['v3'] is None and r['quota_status'] == '']
    out['withheld'] = {'n': len(withheld), 'private': sum(not public(r) for r in withheld)}
    low = [r for r in j2 if r['level'] < 30]
    out['below_30_by_simulated_filling'] = {
        status: {'n': len(s), 'bias_v3': mean(r['eV'] for r in s), 'mae_v3': mae(s, 'eV')}
        for status, s in (('filled', [r for r in low if r['quota_status'] == 'filled']),
                          ('underfilled', [r for r in low if r['quota_status'] == 'underfilled']))}
    sim_under = [r for r in j2 if r['quota_status'] == 'underfilled']
    off_under = [r for r in j2 if official_under(r)]
    out['underfilled'] = {'simulation': len(sim_under), 'official': len(off_under),
                          'both': len([r for r in sim_under if official_under(r)])}
    return out


def level_shift(j2):
    out = {}
    mean_s = mean(r['S'] for r in j2)
    for shift in (-1.0, -0.5, 0.5, 0.8, 1.0, 1.3):
        for centered in (False, True):
            adj = shift - (mean_s + shift if centered else 0)
            g = mean(abs(LAMBDA * (r['eV'] + adj) + (1 - LAMBDA) * r['eH']) - abs(r['eH']) for r in j2)
            out[f"{shift:+.1f}{' centered' if centered else ''}"] = {'gain': g, 'relative': g / mae(j2, 'eH')}
    return out


def contrasts(j2):
    """Differences in the combination's gain between groups (added after the fifth simulated review): each contrast
    is computed within every institution resample, so its interval reflects the shared institution clusters."""
    history = load_history()
    inputs = {d['gid']: d for d in json.loads((PAPER / 'data/baseline-inputs.json').read_text())['departments']}
    rc = {r['gid']: (rule_change(inputs[r['gid']]) if r['gid'] in inputs else None) for r in j2}
    stable_quota = lambda r: bool(history[r['gid']]['quota_2025']) and r['official_quota'] == history[r['gid']]['quota_2025']
    south_east = lambda r: r['region'] in ('south', 'east_and_kinmen')
    groups = {
        'subjects_changed_vs_rules_unchanged': (lambda r: rc[r['gid']] == 'subjects', lambda r: rc[r['gid']] == 'unchanged'),
        'quota_unchanged_vs_changed_among_unchanged_weights': (lambda r: r['unchangedWeights'] and stable_quota(r),
                                                               lambda r: r['unchangedWeights'] and not stable_quota(r)),
        'south_east_kinmen_vs_north_central_below_30': (lambda r: south_east(r) and r['level'] < 30,
                                                        lambda r: not south_east(r) and r['level'] < 30),
        'level_below_30_vs_30_and_above': (lambda r: r['level'] < 30, lambda r: r['level'] >= 30),
        'fewer_than_20_vs_at_least_20_listings': (lambda r: r['applicant_count'] < 20, lambda r: r['applicant_count'] >= 20),
        'private_vs_public': (lambda r: not public(r), lambda r: public(r)),
    }
    out = {}
    for name, (in_a, in_b) in groups.items():
        a = [r for r in j2 if in_a(r)]
        b = [r for r in j2 if in_b(r)]

        def stat(sample, in_a=in_a, in_b=in_b):
            sa = [r for r in sample if in_a(r)]
            sb = [r for r in sample if in_b(r)]
            return gain(sa) - gain(sb) if sa and sb else None
        out[name] = {'n_a': len(a), 'n_b': len(b), 'gain_a': gain(a), 'gain_b': gain(b),
                     'difference': gain(a) - gain(b), 'interval': ci(j2, stat)}
    return out


def support(j2):
    """Gain by listings per place within level bands (added after the fifth simulated review)."""
    from demand_signal import spearman
    out = {}
    for lab, keep in (('below_30', lambda r: r['level'] < 30), ('30_and_above', lambda r: r['level'] >= 30)):
        sub = [r for r in j2 if keep(r)]
        for name, cond in (('lt3', lambda r: r['applicant_count'] / r['official_quota'] < 3),
                           ('ge3', lambda r: r['applicant_count'] / r['official_quota'] >= 3)):
            s = [r for r in sub if r['official_quota'] and cond(r)]
            out[f'{lab}|listings_per_place_{name}'] = {
                'n': len(s), 'institutions': len({r['school'] for r in s}), 'gain': gain(s),
                'relative': mae(s, 'eM') / mae(s, 'eH') - 1, 'bias_v3': mean(r['eV'] for r in s),
                'above_baseline': mean(r['eH'] <= -1 for r in s), 'above_combination': mean(r['eM'] <= -1 for r in s),
                'interval': ci(s, gain) if len({r['school'] for r in s}) >= 5 else None}
        pop = [math.log((r['applicant_count'] + 1) / r['official_quota']) for r in sub if r['official_quota']]
        dd = [r['D'] for r in sub if r['official_quota']]
        ss = [r['S'] for r in sub if r['official_quota']]
        out[f'{lab}|spearman'] = {'S_with_D': spearman(ss, dd), 'popularity_with_D': spearman(pop, dd)}
    return out


def specifications(j2, rows):
    """A specification summary over choices that could have been fixed before the outcomes (added after the fifth
    simulated review): simulator (Fractional or v3), the weights supported by the August backtests, centering of the
    simulated departures on their own mean, five department sets, and four error measures."""
    base_all = [r for r in rows if r['baseline'] is not None and r['actual'] and r['actual'] > 0]
    sets = {'J2': j2, 'J2, at least 20 listings': [r for r in j2 if r['applicant_count'] >= 20],
            'J2, rules unchanged': [r for r in j2 if r['unchangedWeights']],
            'J2, filled by the simulation': [r for r in j2 if r['quota_status'] == 'filled'],
            'all 1,575 with a baseline, fallback': base_all}
    measures = {'MAE': lambda e: mean(abs(x) for x in e), 'RMSE': lambda e: math.sqrt(mean(x * x for x in e)),
                'median absolute error': lambda e: statistics.median(abs(x) for x in e),
                'share at least one grade above': lambda e: mean(x <= -1 for x in e)}
    results = []
    for sim in ('fractional', 'v3'):
        for center in (False, True):
            for set_name, srows in sets.items():
                covered = [r for r in srows if r[sim] is not None]
                shift = mean((r[sim] - r['baseline']) / r['weightTotal'] for r in covered) if center else 0.0
                eh = [(r['baseline'] - r['actual']) / r['weightTotal'] for r in srows]
                for lam in (0.106, 0.3, 0.346, 0.393, 0.4, 0.44):
                    em = []
                    for r in srows:
                        b = (r['baseline'] - r['actual']) / r['weightTotal']
                        if r[sim] is None:
                            em.append(b)
                        else:
                            v = (r[sim] - r['actual']) / r['weightTotal'] - shift
                            em.append(lam * v + (1 - lam) * b)
                    for mname, f in measures.items():
                        h, m = f(eh), f(em)
                        results.append({'simulator': sim, 'centered': center, 'set': set_name, 'lambda': lam,
                                        'measure': mname, 'baseline': h, 'combination': m,
                                        'relative': (m / h - 1) if mname != 'share at least one grade above' else m - h})
    rel = sorted(r['relative'] for r in results)
    q = lambda p: rel[min(len(rel) - 1, int(p * len(rel)))]
    worst = max((r for r in results if r['measure'] == 'MAE'), key=lambda r: r['relative'])
    return {'specifications': len(results), 'improved': sum(r['relative'] < 0 for r in results),
            'relative_quantiles': {'p05': q(0.05), 'p50': q(0.5), 'p95': q(0.95)},
            'mae_relative_range': [min(r['relative'] for r in results if r['measure'] == 'MAE'),
                                   max(r['relative'] for r in results if r['measure'] == 'MAE')],
            'worst_mae': worst, 'results': results}


def _t_quantile(p, df):
    """Cornish-Fisher approximation to the Student t quantile (adequate for df >= 10)."""
    z = statistics.NormalDist().inv_cdf(p)
    return z + (z ** 3 + z) / (4 * df) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * df ** 2)


def _joint_intervals(j2, groups, reps=REPS):
    """Institution-cluster bootstrap of several subgroup gains at once: percentile intervals and simultaneous
    intervals from the maximum absolute standardized deviation (sup-t) across the family."""
    by_school = {}
    for r in j2:
        by_school.setdefault(r['school'], []).append(r)
    keys = sorted(by_school)
    rng = random.Random(SEED)
    est = {name: gain([r for r in j2 if cond(r)]) for name, cond in groups.items()}
    draws = {name: [] for name in groups}
    for _ in range(reps):
        sample = []
        for _ in keys:
            sample.extend(by_school[keys[rng.randrange(len(keys))]])
        for name, cond in groups.items():
            s = [r for r in sample if cond(r)]
            draws[name].append(gain(s) if s else None)
    sd = {}
    for name, vals in draws.items():
        v = [x for x in vals if x is not None]
        sd[name] = statistics.pstdev(v)
    maxima = []
    for k in range(reps):
        zs = [abs(draws[name][k] - est[name]) / sd[name] for name in groups if draws[name][k] is not None and sd[name] > 0]
        if zs:
            maxima.append(max(zs))
    maxima.sort()
    crit = maxima[int(0.95 * len(maxima))]
    out = {'critical_value': crit, 'groups': {}}
    for name in groups:
        v = sorted(x for x in draws[name] if x is not None)
        out['groups'][name] = {'n': sum(1 for r in j2 if groups[name](r)),
                               'institutions': len({r['school'] for r in j2 if groups[name](r)}),
                               'gain': est[name], 'percentile': [v[int(.025 * len(v))], v[int(.975 * len(v))]],
                               'simultaneous': [est[name] - crit * sd[name], est[name] + crit * sd[name]]}
    return out


def fifth_review(j2, rows):
    """Department-level checks requested in the fifth round of simulated reviews (exploratory). All use the released
    department file only."""
    out = {}
    audit = {int(a['gid']): int(a['admitted_including_extra'])
             for a in csv.DictReader((PAPER / 'data/official-rules-audit.csv').open(encoding='utf-8'))}
    under = lambda r: audit[r['gid']] < r['official_quota']

    def describe(s, interval=True):
        if not s:
            return {'n': 0}
        d = {'n': len(s), 'institutions': len({r['school'] for r in s}),
             'mae': {'baseline': mae(s, 'eH'), 'v3': mae(s, 'eV'), 'combination': mae(s, 'eM')},
             'bias': {'baseline': mean(r['eH'] for r in s), 'v3': mean(r['eV'] for r in s),
                      'combination': mean(r['eM'] for r in s)},
             'official_above_by_1': {'baseline': mean(r['eH'] <= -1 for r in s), 'combination': mean(r['eM'] <= -1 for r in s)},
             'official_below_by_1': {'baseline': mean(r['eH'] >= 1 for r in s), 'combination': mean(r['eM'] >= 1 for r in s)},
             'gain': gain(s), 'relative': mae(s, 'eM') / mae(s, 'eH') - 1,
             'fewer_than_20_listings': mean(r['applicant_count'] < 20 for r in s)}
        if interval and d['institutions'] >= 5:
            d['interval'] = ci(s, gain)
        return d

    # 1. Departments that the official allocation left underfilled (admitted, including supernumerary admissions,
    #    below the quota): known only after the results, so a diagnostic.
    all_under = [r for r in rows if under(r)]
    in_j2 = [r for r in j2 if under(r)]
    flagged_up = [r for r in in_j2 if r['S'] >= 1]
    out['official_underfilled'] = {
        'all_1706': {'n': len(all_under), 'vacancies': sum(r['official_quota'] - audit[r['gid']] for r in all_under),
                     'institutions': len({r['school'] for r in all_under}),
                     'withheld_fewer_than_5_listings': sum(r['applicant_count'] < 5 for r in all_under),
                     'rate_among_withheld': mean(under(r) for r in rows if r['applicant_count'] < 5),
                     'rate_among_others': mean(under(r) for r in rows if r['applicant_count'] >= 5)},
        'J2': describe(in_j2),
        'J2_simulation_not_filled': sum(r['quota_status'] != 'filled' for r in in_j2),
        'J2_upward_flags': {'n': len(flagged_up), 'moved_up_1': sum(r['D'] >= 1 for r in flagged_up),
                            'moved_down_1': sum(r['D'] <= -1 for r in flagged_up)},
    }
    sim_not_filled = [r for r in j2 if r['quota_status'] != 'filled']
    out['simulated_filling_status'] = {'not_filled_in_J2': len(sim_not_filled),
                                       'officially_underfilled': sum(under(r) for r in sim_not_filled),
                                       'private': sum(not public(r) for r in sim_not_filled)}

    # 2. Level below 30 by region, separating the south from the east and Kinmen; private southern departments.
    low = [r for r in j2 if r['level'] < 30]
    out['below_30_by_region'] = {reg: describe([r for r in low if r['region'] == reg])
                                 for reg in ('north', 'central', 'south', 'east_and_kinmen')}
    out['below_30_south_private'] = describe([r for r in low if r['region'] == 'south' and not public(r)], interval=False)
    out['below_30_south_public'] = describe([r for r in low if r['region'] == 'south' and public(r)], interval=False)
    out['level_bands'] = {f'{lo}-{hi}': describe([r for r in j2 if lo <= r['level'] < hi]) for lo, hi in LEVEL_BANDS}

    # 3. Simultaneous intervals for the family of subgroup gains in Table 5.
    family = {f'level {lo}-{hi}': (lambda r, lo=lo, hi=hi: lo <= r['level'] < hi) for lo, hi in LEVEL_BANDS}
    for reg in ('north', 'central', 'south', 'east_and_kinmen'):
        family[f'below 30, {reg}'] = lambda r, reg=reg: r['level'] < 30 and r['region'] == reg
    out['table5_family'] = _joint_intervals(j2, family)

    # 4. Flags by level and sector, and their reliability.
    def flag_stats(s):
        up = [r for r in s if r['S'] >= 1]
        down = [r for r in s if r['S'] <= -1]
        return {'n': len(s), 'up_flag_share': mean(r['S'] >= 1 for r in s), 'down_flag_share': mean(r['S'] <= -1 for r in s),
                'up_precision': mean(r['D'] >= 1 for r in up), 'up_moved_down_1': mean(r['D'] <= -1 for r in up),
                'down_precision': mean(r['D'] <= -1 for r in down), 'down_moved_up_1': mean(r['D'] >= 1 for r in down)}
    out['flags_by_level_and_sector'] = {
        f'{lv}|{sec}': flag_stats([r for r in j2 if (r['level'] < 30) == (lv == 'below_30') and public(r) == (sec == 'public')])
        for lv in ('below_30', '30_and_above') for sec in ('public', 'private')}
    out['flags_by_level_and_sector']['below_30|south_east_kinmen'] = flag_stats(
        [r for r in low if r['region'] in ('south', 'east_and_kinmen')])

    # 5. Moves in the flagged direction, against S permuted within deciles of historical level.
    def move_stats(key):
        flagged = [r for r in j2 if abs(r[key]) >= 1]
        nonzero = [r for r in flagged if r['D'] != 0]
        up = [r for r in j2 if r[key] >= 1]
        down = [r for r in j2 if r[key] <= -1]
        return {'flagged': len(flagged),
                'sign_agreement': mean((r[key] > 0) == (r['D'] > 0) for r in nonzero),
                'moved_1_in_flagged_direction': mean((r['D'] >= 1) if r[key] > 0 else (r['D'] <= -1) for r in flagged),
                'moved_1_against': mean((r['D'] <= -1) if r[key] > 0 else (r['D'] >= 1) for r in flagged),
                'up_precision': mean(r['D'] >= 1 for r in up), 'down_precision': mean(r['D'] <= -1 for r in down)}
    observed = move_stats('S')
    departures = [r for r in j2 if abs(r['D']) >= 1]
    observed['departures_of_1'] = len(departures)
    observed['departures_flagged_same_direction'] = sum((r['S'] >= 1) if r['D'] > 0 else (r['S'] <= -1) for r in departures)
    deciles = {}
    order = sorted(j2, key=lambda r: r['level'])
    for k, r in enumerate(order):
        deciles.setdefault(10 * k // len(order), []).append(r)
    rng = random.Random(SEED)
    ref = {k: [] for k in ('sign_agreement', 'moved_1_in_flagged_direction', 'moved_1_against', 'up_precision', 'down_precision')}
    for _ in range(2000):
        for members in deciles.values():
            s = [r['S'] for r in members]
            rng.shuffle(s)
            for r, v in zip(members, s):
                r['S_perm'] = v
        res = move_stats('S_perm')
        for k in ref:
            ref[k].append(res[k])
    out['flag_moves'] = {'observed': observed, 'permuted_within_level_deciles': {
        k: {'mean': statistics.fmean(v), 'interval': [sorted(v)[50], sorted(v)[1949]]} for k, v in ref.items()}}

    # 6. Intervals: a common shift in next year's errors, widening, the baseline's own interval, subgroups.
    for r in j2:
        r['err'] = r['eM']
        r['x'] = [math.log(r['applicant_count'] + 1), r['level'], (r['level'] - 40) ** 2]
    combo = intervals(j2, 0.80, 'scaled')
    width = statistics.median(hi - lo for _, lo, hi in combo)
    shifts = {}
    for d in (-1.17, -0.70, -0.35, 0.0, 0.35, 0.70):
        for pad in (0.0, 0.7):
            e = [(r['err'] + d, lo - pad, hi + pad) for r, lo, hi in combo]
            shifts[f'shift {d:+.2f}, pad {pad:.1f}'] = {
                'coverage': mean(lo <= x <= hi for x, lo, hi in e), 'official_above': mean(x < lo for x, lo, hi in e),
                'official_below': mean(x > hi for x, lo, hi in e)}
    equal = intervals(j2, 0.80, 'scaled_equal_tailed')
    for r in j2:
        r['err'] = r['eH']
    base = intervals(j2, 0.80, 'scaled')
    for r in j2:
        r['err'] = r['eM']
    out['intervals'] = {
        'median_width_combination': width, 'median_width_baseline_same_model': statistics.median(hi - lo for _, lo, hi in base),
        'coverage_baseline_same_model': mean(lo <= r['eH'] <= hi for r, lo, hi in base),
        'equal_tailed': {'median_width': statistics.median(hi - lo for _, lo, hi in equal),
                         'coverage': mean(lo <= r['eM'] <= hi for r, lo, hi in equal),
                         'official_above': mean(r['eM'] < lo for r, lo, hi in equal),
                         'official_below': mean(r['eM'] > hi for r, lo, hi in equal)},
        'common_shift': shifts}
    cover = {id(r): (lo <= r['eM'] <= hi, r['eM'] < lo) for r, lo, hi in combo}
    sub = {'fewer_than_20_listings': lambda r: r['applicant_count'] < 20, 'level_below_30': lambda r: r['level'] < 30,
           'private': lambda r: not public(r),
           'south_east_kinmen_below_30': lambda r: r['level'] < 30 and r['region'] in ('south', 'east_and_kinmen'),
           'abs_S_at_least_4': lambda r: abs(r['S']) >= 4}
    out['interval_subgroups'] = {}
    for name, cond in sub.items():
        s = [r for r in j2 if cond(r)]
        out['interval_subgroups'][name] = {
            'n': len(s), 'institutions': len({r['school'] for r in s}), 'coverage': mean(cover[id(r)][0] for r in s),
            'official_above': mean(cover[id(r)][1] for r in s),
            'interval': ci(s, lambda smp: mean(cover[id(r)][0] for r in smp))}
    half = width / 2
    v_only = [r for r in rows if r['v3'] is not None and r['baseline'] is None and r['actual'] and r['actual'] > 0]
    b_only = [r for r in rows if r['v3'] is None and r['baseline'] is not None and r['actual'] and r['actual'] > 0]
    e_v = [(r['v3'] - r['actual']) / r['weightTotal'] for r in v_only]
    e_b = [(r['baseline'] - r['actual']) / r['weightTotal'] for r in b_only]
    out['single_source'] = {
        'v3_only': {'n': len(e_v), 'mae': mean(abs(x) for x in e_v), 'bias': mean(e_v),
                    'coverage_with_median_J2_half_width': mean(abs(x) <= half for x in e_v)},
        'baseline_only': {'n': len(e_b), 'mae': mean(abs(x) for x in e_b), 'bias': mean(e_b),
                          'coverage_with_median_J2_half_width': mean(abs(x) <= half for x in e_b)}}

    # 7. The combination rule as deployed would apply it: blend where both exist, otherwise the available one.
    anyp = [r for r in rows if (r['v3'] is not None or r['baseline'] is not None) and r['actual'] and r['actual'] > 0]
    def fallback(r):
        if r['v3'] is not None and r['baseline'] is not None:
            return LAMBDA * r['v3'] + (1 - LAMBDA) * r['baseline']
        return r['v3'] if r['v3'] is not None else r['baseline']
    with_base = [r for r in anyp if r['baseline'] is not None]
    out['fallback_rule'] = {
        'n_any_prediction': len(anyp), 'mae_fallback': mean(abs(fallback(r) - r['actual']) / r['weightTotal'] for r in anyp),
        'n_with_baseline': len(with_base),
        'mae_baseline': mean(abs(r['baseline'] - r['actual']) / r['weightTotal'] for r in with_base),
        'mae_fallback_on_baseline_set': mean(abs(fallback(r) - r['actual']) / r['weightTotal'] for r in with_base)}

    # 8. A stricter release threshold: departments with at least 10 or 20 listings.
    def headline(s):
        flagged = [r for r in s if abs(r['S']) >= 1 and r['D'] != 0]
        return {'n': len(s), 'institutions': len({r['school'] for r in s}), 'mae_baseline': mae(s, 'eH'),
                'mae_combination': mae(s, 'eM'), 'relative': mae(s, 'eM') / mae(s, 'eH') - 1,
                'above_baseline': mean(r['eH'] <= -1 for r in s), 'above_combination': mean(r['eM'] <= -1 for r in s),
                'sign_agreement': mean((r['S'] > 0) == (r['D'] > 0) for r in flagged)}
    out['release_threshold'] = {f'at least {t} listings': headline([r for r in j2 if r['applicant_count'] >= t])
                                for t in (5, 10, 20)}
    grid = lambda v: v is not None and abs(v * 4 - round(v * 4)) < 1e-9
    out['release_threshold']['values_on_quarter_grid'] = {
        k: {'released': sum(r[k] is not None for r in rows), 'on_grid': sum(grid(r[k]) for r in rows),
            'on_grid_fewer_than_20_listings': sum(grid(r[k]) and r['applicant_count'] < 20 for r in rows)}
        for k in ('v1', 'v2', 'fractional', 'v3')}
    out['release_threshold']['v3_equal_to_fractional'] = {
        'n': sum(r['v3'] is not None and r['v3'] == r['fractional'] for r in rows),
        'fewer_than_20_listings': sum(r['v3'] is not None and r['v3'] == r['fractional'] and r['applicant_count'] < 20 for r in rows)}

    # 9. Heterogeneity across institutions (paired difference per institution, DerSimonian-Laird).
    by_school = {}
    for r in j2:
        by_school.setdefault(r['school'], []).append(abs(r['eM']) - abs(r['eH']))
    stats_ = [(statistics.fmean(v), statistics.variance(v) / len(v)) for v in by_school.values() if len(v) >= 2]
    w = [1 / v for _, v in stats_ if v > 0]
    y = [m for m, v in stats_ if v > 0]
    fixed = sum(wi * yi for wi, yi in zip(w, y)) / sum(w)
    q = sum(wi * (yi - fixed) ** 2 for wi, yi in zip(w, y))
    k = len(y)
    tau2 = max(0.0, (q - (k - 1)) / (sum(w) - sum(wi * wi for wi in w) / sum(w)))
    wr = [1 / (v + tau2) for _, v in stats_ if v > 0]
    mu = sum(wi * yi for wi, yi in zip(wr, y)) / sum(wr)
    se = math.sqrt(1 / sum(wr))
    t = _t_quantile(0.975, k - 2)
    out['institution_heterogeneity'] = {
        'institutions': len(by_school), 'worse_with_combination': sum(statistics.fmean(v) > 0 for v in by_school.values()),
        'used_in_meta_analysis': k, 'random_effects_mean': mu, 'tau': math.sqrt(tau2), 'I2': max(0.0, (q - (k - 1)) / q),
        'prediction_interval': [mu - t * math.sqrt(tau2 + se * se), mu + t * math.sqrt(tau2 + se * se)]}
    return out


def main():
    rows = load_rows()
    j2 = common_rows(rows, ('v3', 'baseline'))
    for r in j2:
        errors(r)
        r['region'] = region_of(r)
    history = load_history()
    out = {'note': 'exploratory; added after the fourth round of simulated pre-submission reviews', 'n_J2': len(j2),
           'tails': tails(j2), 'slopes': slopes(j2), 'structure': structure(j2), 'accuracy': accuracy(rows, j2),
           'decision': decision(j2, history), 'equity': equity(rows, j2), 'level_shift': level_shift(j2),
           'contrasts': contrasts(j2), 'support': support(j2), 'specifications': specifications(j2, rows),
           'fifth_review': fifth_review(j2, rows)}
    output_path('revision-checks.json').write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(out, indent=1, ensure_ascii=False)[:6000])


if __name__ == '__main__':
    main()
