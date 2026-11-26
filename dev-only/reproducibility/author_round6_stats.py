"""Aggregates of the checks added after the sixth round of simulated reviews (exploratory; plan v0.25).

Runs only on the author's computer. It reads the aggregates that author_checks_round6.mjs wrote to OUT_DIR, the
department-level values that it wrote to PRIVATE_DIR, and, for item G4 of the plan, department-level outputs of the
earlier reruns (PRIOR_PRIVATE_DIR); it merges them with the statistics below into data/author-checks-round6.json, which
holds aggregates only. Intervals resample institutions 4,000 times with the seed of the main text (20260922) on the
released J2 set; the combination falls back to the baseline where a variant gives no value.

  synthetic    gains with the records' own preferences (rerun) and with generated lists, and their paired difference;
  quota2025    the gain with 2025 quotas, and the regression of D on the quota part and the rest of S;
  earliest     the gain with each account's earliest saved list, paired with the rerun;
  centered     raw and self-centered gains of earlier frame, scaling and truncation reruns;
  halves       per-department sampling variance from 40 delete-half replicates, its share of v3's squared error by
               support, and the standard deviation of subgroup gains across replicates;
  neff         Kish effective sample size of the eligible listers against v3's error;
  placements   Wilson intervals for the shares of records placed more favorably than by the official cutoffs.

Usage: OUT_DIR=... PRIVATE_DIR=... PRIOR_PRIVATE_DIR=... python3 author_round6_stats.py
"""
import csv
import hashlib
import json
import math
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, load_rows, common_rows  # noqa: E402
from history_checks import load_history  # noqa: E402
from revision_checks import LAMBDA, LEVEL_BANDS, ci, errors, mean, public, region_of  # noqa: E402

OUT = Path(os.environ['OUT_DIR'])
PRIVATE = Path(os.environ['PRIVATE_DIR'])
PRIOR = Path(os.environ['PRIOR_PRIVATE_DIR'])
HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dept(path, column='prediction'):
    with open(path, encoding='utf-8') as handle:
        return {int(r['gid']): float(r[column]) for r in csv.DictReader(handle) if r.get(column) not in ('', None)}


rows = load_rows()
J2 = common_rows(rows, ('v3', 'baseline'))
for r in J2:
    errors(r)
    r['region'] = region_of(r)
assert len(J2) == 1521
history = load_history()
STABLE = {r['gid'] for r in J2 if r['unchangedWeights'] and history[r['gid']]['quota_2025']
          and r['official_quota'] == history[r['gid']]['quota_2025']}
assert len(STABLE) == 167


def attach(pred, key):
    """Error of the variant (v_key), of its combination with the baseline (m_key; baseline where missing) and S_key."""
    for r in J2:
        v = pred.get(r['gid'])
        if v is None:
            r['v_' + key], r['s_' + key], r['m_' + key] = None, None, r['eH']
        else:
            ev = (v - r['actual']) / r['weightTotal']
            r['v_' + key], r['s_' + key] = ev, (v - r['baseline']) / r['weightTotal']
            r['m_' + key] = LAMBDA * ev + (1 - LAMBDA) * r['eH']


def gain_of(key):
    return lambda s: mean(abs(r['m_' + key]) - abs(r['eH']) for r in s)


def paired(a, b):
    return lambda s: mean(abs(r['m_' + a]) - abs(r['m_' + b]) for r in s)


def agreement(key, rows_=None):
    flagged = [r for r in (rows_ or J2) if r['s_' + key] is not None and abs(r['s_' + key]) >= 1 and r['D'] != 0]
    return {'flagged': len(flagged), 'agreement': mean((r['s_' + key] > 0) == (r['D'] > 0) for r in flagged) if flagged else None}


def summary(key):
    covered = [r for r in J2 if r['v_' + key] is not None]
    low = [r for r in covered if r['level'] < 30]
    return {'covered': len(covered), 'mae_alone': mean(abs(r['v_' + key]) for r in covered),
            'bias_alone': mean(r['v_' + key] for r in covered), 'bias_below_level_30': mean(r['v_' + key] for r in low),
            'mae_combination': mean(abs(r['m_' + key]) for r in J2), 'gain': gain_of(key)(J2), 'gain_interval': ci(J2, gain_of(key)),
            'relative': mean(abs(r['m_' + key]) for r in J2) / mean(abs(r['eH']) for r in J2) - 1,
            'mean_S': mean(r['s_' + key] for r in covered), **agreement(key),
            'official_above_combination_by_a_grade': mean(r['m_' + key] <= -1 for r in J2)}


def ols2(sample, x1, x2):
    """Least squares of D on an intercept, x1 and x2; returns the two slopes."""
    n = len(sample)
    m = [mean(r[k] for r in sample) for k in ('D', x1, x2)]
    a = [[r[x1] - m[1], r[x2] - m[2]] for r in sample]
    y = [r['D'] - m[0] for r in sample]
    s11 = sum(u[0] * u[0] for u in a); s22 = sum(u[1] * u[1] for u in a); s12 = sum(u[0] * u[1] for u in a)
    t1 = sum(u[0] * v for u, v in zip(a, y)); t2 = sum(u[1] * v for u, v in zip(a, y))
    det = s11 * s22 - s12 * s12
    if n < 3 or det == 0:
        return None
    return ((s22 * t1 - s12 * t2) / det, (s11 * t2 - s12 * t1) / det)


def wilson(k, n, z=1.959963984540054):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [c - h, c + h]


def newcombe(k1, n1, k2, n2):
    """Newcombe's hybrid score interval for p1 - p2."""
    l1, u1 = wilson(k1, n1)
    l2, u2 = wilson(k2, n2)
    p1, p2 = k1 / n1, k2 / n2
    d = p1 - p2
    return [d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)]


out = {'note': 'exploratory (plan v0.25, written before these computations); aggregates only', 'n_J2': len(J2),
       'plan_sha256': sha(PAPER / 'dev-only/review/analysis-plan-v025.md'),
       'scripts': {'author_checks_round6.mjs': sha(HERE / 'author_checks_round6.mjs'), 'author_round6_stats.py': sha(__file__)}}
sections = {}
for name in ('engine', 'synthetic', 'placements6', 'quota2025', 'earliest', 'tilt6', 'small'):
    data = json.loads((OUT / f'author-checks-{name}.json').read_text())
    sections[name] = data
out['provenance'] = {k: {'computedAt': v['computedAt'], 'inputs': v['inputs'], 'provenance': v['provenance']} for k, v in sections.items()}
out['engine_tally'] = sections['engine']['tally']

# A. The production engine and the August rule (department values stay with the author; see the plan).
engine = {}
with open(PRIVATE / 'dept-engine.csv', encoding='utf-8') as handle:
    for r in csv.DictReader(handle):
        engine[int(r['gid'])] = {k: (float(v) if v not in ('', None) else None) for k, v in r.items() if k != 'gid'}
for r in J2:
    e = engine.get(r['gid'], {})
    for key in ('engineBase', 'engineFinal', 'backtestPrior', 'augustRule', 'augustRuleEngine'):
        v = e.get(key)
        r['x_' + key] = None if v is None else (v - r['actual']) / r['weightTotal']
    ef = r['x_engineFinal']
    r['x_scoreMixEngine'] = None if ef is None else LAMBDA * r['eV'] + (1 - LAMBDA) * ef
    r['x_paperCombination'] = r['eM']
    r['x_baseline'] = r['eH']
ENGINE_SET = [r for r in J2 if all(r['x_' + k] is not None for k in ('engineBase', 'engineFinal', 'backtestPrior', 'augustRule', 'augustRuleEngine'))]


def x_summary(key, s):
    return {'mae': mean(abs(r['x_' + key]) for r in s), 'bias': mean(r['x_' + key] for r in s),
            'official_above_by_a_grade': mean(r['x_' + key] <= -1 for r in s), 'official_below_by_a_grade': mean(r['x_' + key] >= 1 for r in s)}


def x_diff(a, b):
    return lambda s: mean(abs(r['x_' + a]) - abs(r['x_' + b]) for r in s)


comparisons = {'august_rule_engine_minus_engine_final': ('augustRuleEngine', 'engineFinal'),
               'august_rule_minus_backtest_prior': ('augustRule', 'backtestPrior'),
               'paper_combination_minus_engine_final': ('paperCombination', 'engineFinal'),
               'score_mix_with_engine_minus_engine_final': ('scoreMixEngine', 'engineFinal'),
               'engine_final_minus_baseline': ('engineFinal', 'baseline'),
               'engine_base_minus_baseline': ('engineBase', 'baseline'),
               'august_rule_engine_minus_paper_combination': ('augustRuleEngine', 'paperCombination')}
out['engine'] = {
    'n': len(ENGINE_SET), 'institutions': len({r['school'] for r in ENGINE_SET}),
    'methods': {k: x_summary(k, ENGINE_SET) for k in ('baseline', 'engineBase', 'engineFinal', 'backtestPrior', 'augustRule',
                                                      'augustRuleEngine', 'paperCombination', 'scoreMixEngine')},
    'differences': {name: {'difference': x_diff(a, b)(ENGINE_SET), 'relative': x_summary(a, ENGINE_SET)['mae'] / x_summary(b, ENGINE_SET)['mae'] - 1,
                           'interval': ci(ENGINE_SET, x_diff(a, b))} for name, (a, b) in comparisons.items()},
    'by_structure': {label: (lambda s: {'n': len(s), 'engine_final_mae': x_summary('engineFinal', s)['mae'],
                                         'baseline_mae': x_summary('baseline', s)['mae'],
                                         'august_rule_engine_minus_engine_final': x_diff('augustRuleEngine', 'engineFinal')(s),
                                         'interval': ci(s, x_diff('augustRuleEngine', 'engineFinal')) if len({r['school'] for r in s}) >= 5 else None})(
        [r for r in ENGINE_SET if f(r)]) for label, f in (
            ('rules_changed', lambda r: not r['unchangedWeights']),
            ('rules_unchanged_quota_changed', lambda r: r['unchangedWeights'] and r['gid'] not in STABLE),
            ('rules_and_quota_unchanged', lambda r: r['gid'] in STABLE))},
    'tally': sections['engine']['tally']}

# B. Generated preference lists.
attach(dept(PRIVATE / 'dept-synthetic-real.csv'), 'real')
attach(dept(PRIVATE / 'dept-synthetic-ownLength.csv'), 'own')
attach(dept(PRIVATE / 'dept-synthetic-fiftyFive.csv'), 'f55')
out['synthetic'] = {'records_rerun_with_own_preferences': summary('real'), 'generated_lists_own_length': summary('own'),
                    'generated_lists_55': summary('f55'),
                    'own_minus_generated': {'difference': paired('real', 'own')(J2), 'interval': ci(J2, paired('real', 'own'))},
                    'list_details': sections['synthetic']['variants'], 'mean_overlap_with_real_list': sections['synthetic']['meanOverlapWithRealList']}
for k in ('real', 'own', 'f55'):
    out['synthetic'][{'real': 'records_rerun_with_own_preferences', 'own': 'generated_lists_own_length', 'f55': 'generated_lists_55'}[k]]['stable_167_gain'] = \
        gain_of(k)([r for r in J2 if r['gid'] in STABLE])

# D. 2025 quotas.
attach(dept(PRIVATE / 'dept-quota2025.csv', 'real'), 'q26')
attach(dept(PRIVATE / 'dept-quota2025.csv', 'prediction'), 'q25')
both = [r for r in J2 if r['s_q26'] is not None and r['s_q25'] is not None]
for r in both:
    r['s_quota'] = r['s_q26'] - r['s_q25']
    r['s_rest'] = r['s_q25']
slope = lambda i: (lambda s: (lambda b: None if b is None else b[i])(ols2(s, 's_quota', 's_rest')))
out['quota2025'] = {'quota_2026': summary('q26'), 'quota_2025': summary('q25'),
                    'difference_2026_minus_2025_quotas': {'difference': paired('q26', 'q25')(J2), 'interval': ci(J2, paired('q26', 'q25'))},
                    'decomposition': {'n': len(both), 'slope_quota_part': slope(0)(both), 'slope_quota_part_interval': ci(both, slope(0)),
                                      'slope_rest': slope(1)(both), 'slope_rest_interval': ci(both, slope(1)),
                                      'sd_quota_part': statistics.pstdev(r['s_quota'] for r in both),
                                      'sd_rest': statistics.pstdev(r['s_rest'] for r in both)},
                    'departments_with_changed_quota': sections['quota2025']['departmentsWithChangedQuota']}

# E. Earliest lists.
attach(dept(PRIVATE / 'dept-earliest.csv'), 'early')
out['earliest'] = {'earliest_lists': summary('early'),
                   'earliest_minus_rerun': {'difference': paired('early', 'real')(J2), 'interval': ci(J2, paired('early', 'real'))},
                   'linked_accounts': sections['earliest']['linkedAccounts'], 'accounts_whose_list_changed': sections['earliest']['accountsWhoseListChanged'],
                   'first_run_of_accounts': sections['earliest']['firstRunOfAccounts'], 'added': sections['earliest']['added'],
                   'removed': sections['earliest']['removed'], 'counts': sections['earliest']['counts']}

# F. Tilts (points from the rerun script).
out['tilt'] = [{'group': t['group'], 'gamma': t['gamma'], 'records': t['records'], 'converged': t['converged'],
                'weighted_share': t['weightedShare'], 'production_share': t['productionShare'], 'gain': t['j2']['mixMinusBaseline'],
                'direction_agreement': t['j2']['directionAgreement'], 'flagged': t['j2']['flagged'],
                'bias_below_level_30': t['j2']['biasBelowLevel30']} for t in sections['tilt6']['results']]

# G4. Self-centered versions of earlier reruns.
centered = {}
for label, file in (('main', 'dept-variant-main.csv'), ('registrant_scaled', 'dept-variant-registrant-scaled.csv'),
                    ('remove_top_2840', 'dept-participation-top.csv'), ('remove_bottom_2840', 'dept-participation-bottom.csv'),
                    ('truncate_10', 'dept-variant-truncate-10.csv'), ('truncate_20', 'dept-variant-truncate-20.csv'),
                    ('truncate_40', 'dept-variant-truncate-40.csv')):
    path = PRIOR / file
    if not path.exists():
        centered[label] = None
        continue
    pred = dept(path)
    attach(pred, 'c')
    raw = summary('c')
    shift = raw['mean_S']
    weight_total = {r['gid']: r['weightTotal'] for r in J2}
    attach({g: v - shift * weight_total[g] for g, v in pred.items() if g in weight_total}, 'cc')
    centered[label] = {'raw_gain': raw['gain'], 'raw_interval': raw['gain_interval'], 'mean_S': shift,
                       'centered_gain': gain_of('cc')(J2), 'centered_interval': ci(J2, gain_of('cc')),
                       'raw_agreement': raw['agreement'], 'raw_official_above': raw['official_above_combination_by_a_grade'],
                       'centered_official_above': mean(r['m_cc'] <= -1 for r in J2)}
out['centered'] = centered

# G5. Delete-half replicates with department-level values.
halves = []
k = 0
while (PRIVATE / f'dept-half6-{k}.csv').exists():
    halves.append(dept(PRIVATE / f'dept-half6-{k}.csv'))
    k += 1
if halves:
    K = len(halves)
    by_gid = {r['gid']: r for r in J2}
    psi = {}
    for g, r in by_gid.items():
        vals = [(h[g] - r['actual']) / r['weightTotal'] for h in halves if g in h]
        if len(vals) >= 20:
            mu = sum(vals) / len(vals)
            psi[g] = sum((v - mu) ** 2 for v in vals) / len(vals)
    bands = ((0, 20), (20, 40), (40, 80), (80, 160), (160, 10 ** 9))
    by_band = []
    for lo, hi in bands:
        s = [r for r in J2 if lo <= r['applicant_count'] < hi and r['gid'] in psi]
        by_band.append({'listings': [lo, hi if hi < 10 ** 9 else None], 'n': len(s), 'mean_psi': mean(psi[r['gid']] for r in s),
                        'mean_squared_error_v3': mean(r['eV'] ** 2 for r in s),
                        'sampling_share': mean(psi[r['gid']] for r in s) / mean(r['eV'] ** 2 for r in s),
                        'median_sd': statistics.median(math.sqrt(psi[r['gid']]) for r in s)})
    groups = {'all': lambda r: True, 'stable_167': lambda r: r['gid'] in STABLE,
              **{f'level_{lo}_{hi}': (lambda r, lo=lo, hi=hi: lo <= r['level'] < hi) for lo, hi in LEVEL_BANDS},
              **{f'below_30_{g}': (lambda r, g=g: r['level'] < 30 and r['region'] == g) for g in ('north', 'central', 'south', 'east_and_kinmen')},
              'below_30_south_private': lambda r: r['level'] < 30 and r['region'] == 'south' and not public(r)}
    sds = {}
    for name, f in groups.items():
        s = [r for r in J2 if f(r)]
        gains = []
        for h in halves:
            vals = []
            for r in s:
                v = h.get(r['gid'])
                m = r['eH'] if v is None else LAMBDA * (v - r['actual']) / r['weightTotal'] + (1 - LAMBDA) * r['eH']
                vals.append(abs(m) - abs(r['eH']))
            gains.append(mean(vals))
        sds[name] = {'n': len(s), 'mean_gain_in_halves': mean(gains), 'sd_across_halves': statistics.pstdev(gains)}
    out['halves'] = {'replicates': K, 'records_per_replicate': 2313, 'departments_with_psi': len(psi),
                     'median_sampling_sd_v3': statistics.median(math.sqrt(v) for v in psi.values()),
                     'by_listings': by_band, 'subgroup_gain_sd': sds,
                     'note': 'delete-half jackknife: the variance across half-samples estimates the sampling variance of the full-sample value'}

# G3. Effective sample size.
neff = dept(PRIVATE / 'dept-neff.csv', 'neff')


def rank(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for t in range(i, j + 1):
            ranks[order[t]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x, y):
    rx, ry = rank(x), rank(y)
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    return num / math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))


have = [r for r in J2 if r['gid'] in neff]
terciles = sorted(neff[r['gid']] for r in have)
cuts = (terciles[len(terciles) // 3], terciles[2 * len(terciles) // 3])
lcuts = sorted(r['applicant_count'] for r in have)
lcuts = (lcuts[len(lcuts) // 3], lcuts[2 * len(lcuts) // 3])
tercile = lambda x, c: 0 if x < c[0] else 1 if x < c[1] else 2
out['neff'] = {'n': len(have), 'summary': sections['small']['neffOnJ2'],
               'spearman_neff_abs_error_v3': spearman([neff[r['gid']] for r in have], [abs(r['eV']) for r in have]),
               'spearman_listings_abs_error_v3': spearman([r['applicant_count'] for r in have], [abs(r['eV']) for r in have]),
               'spearman_neff_listings': spearman([neff[r['gid']] for r in have], [r['applicant_count'] for r in have]),
               'gain_by_neff_tercile': [{'cut': list(cuts), 'tercile': t, 'n': len(s), 'gain': mean(abs(r['eM']) - abs(r['eH']) for r in s),
                                         'mae_v3': mean(abs(r['eV']) for r in s)}
                                        for t in range(3) for s in [[r for r in have if tercile(neff[r['gid']], cuts) == t]]],
               'gain_by_listing_tercile': [{'cut': list(lcuts), 'tercile': t, 'n': len(s), 'gain': mean(abs(r['eM']) - abs(r['eH']) for r in s),
                                            'mae_v3': mean(abs(r['eV']) for r in s)}
                                           for t in range(3) for s in [[r for r in have if tercile(r['applicant_count'], lcuts) == t]]]}

# C. Placements with Wilson intervals for the lowest and highest fifth (unweighted record counts).
placements = sections['placements6']['report']
for label, rep in placements.items():
    for method, table in rep['byMethod'].items():
        lo, hi = table['1'], table['5']
        table['intervals'] = {
            'earlier_lowest_fifth': wilson(lo['earlier'], lo['records']), 'earlier_highest_fifth': wilson(hi['earlier'], hi['records']),
            'earlier_difference_lowest_minus_highest': newcombe(lo['earlier'], lo['records'], hi['earlier'], hi['records']),
            'predicted_only_lowest_fifth': wilson(lo['predictedOnly'], lo['records']),
            'predicted_only_highest_fifth': wilson(hi['predictedOnly'], hi['records']),
            'same_all': wilson(table['all']['same'], table['all']['records'])}
out['placements'] = placements
out['returners'] = sections['small']['returners']
out['run_content_hashes'] = sections['small']['runContentHashes']

target = PAPER / 'data/author-checks-round6.json'
target.write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'wrote': str(target), 'sha256': sha(target)}))
