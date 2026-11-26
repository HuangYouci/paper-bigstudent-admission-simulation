"""Supplement S32 (checks added after the sixth simulated review) from stored outputs, rounding once.

Reads data/author-checks-round6.json (record-level and engine aggregates) and data/sixth-review.json (department-level
checks) and writes out/s32.md.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, output_path  # noqa: E402

A = json.loads((PAPER / 'data/author-checks-round6.json').read_text())
H = json.loads((PAPER / 'data/sixth-review.json').read_text())


def g(x, d=2, sign=True):
    if x is None:
        return '—'
    s = f'{x:+.{d}f}' if sign else f'{x:.{d}f}'
    return s.replace('-', '−')


def iv(v, d=2):
    return '—' if v is None else f'[{g(v[0], d)}, {g(v[1], d)}]'


def pct(x, d=1, sign=False):
    if x is None:
        return '—'
    s = f'{100 * x:+.{d}f}%' if sign else f'{100 * x:.{d}f}%'
    return s.replace('-', '−')


def n(x):
    return f'{x:,}'


def label_of(text):
    """Readable labels without characters that break table cells."""
    t = text.replace('_', ' ').replace('east and kinmen', 'east and Kinmen')
    t = t.replace('|dlog q| <= 0.05', 'quota change above 0, at most 0.05')
    t = t.replace('rules unchanged, 0.05-0.35 (the two middle bins together)', 'rules unchanged, quota change 0.05–0.35 (middle bins together)')
    t = t.replace('rules unchanged, 0.05-0.15', 'rules unchanged, quota change 0.05–0.15')
    t = t.replace('rules unchanged, 0.15-0.35', 'rules unchanged, quota change 0.15–0.35')
    t = t.replace('rules unchanged, > 0.35', 'rules unchanged, quota change above 0.35')
    t = re.sub(r'(\d)-(\d)', '\\1–\\2', t)
    t = re.sub(r'(^|[ =(])-(\d)', '\\1−\\2', t)
    return t.replace('|', '/')


out = []
w = out.append
w('## S32 Checks added after the sixth simulated review')
w('')
w('Plan v0.25 (`dev-only/review/analysis-plan-v025.md`, 26 November 2026, 02:50 Taiwan time) specified these checks after a sixth round of simulated reviews and before any of them was computed; all are exploratory. `author_checks_round6.mjs` reruns the platform functions on the frozen database and, where records are needed, on the pseudonymized export; `author_round6_stats.py` computes the reported statistics and writes only aggregates to `data/author-checks-round6.json`; `sixth_review.py` computes the department-level checks from the released files (`data/sixth-review.json`); `s32_tables.py` builds the tables below. Intervals resample institutions 4,000 times (seed 20260922) on the released $\\mathcal J_2$ set.')
w('')

# S32a Engine.
E = A['engine']
w('**The production engine.** The engine pairs each 2026 department with its most recent earlier year that has an admission score (2025 for 1,575 departments, 2024 for 19), converts that cutoff to the 2026 subjects with `rebuildWeightedThreshold` (unchanged for {} departments, rebuilt for {}), and, when the earlier year is 2025, adds `adjustCutoffDeltaTByQuota`, a shift in proportion to a power of the relative change in quota that is larger at lower percentiles ({} departments; {} had an unchanged quota). It compares a user\'s grades, equated subject by subject to the earlier year, with that cutoff. We map each engine cutoff to the 2026 scale at the same percentile of the department\'s distribution (`weightedPrAtScore`, `weightedScoreAtPrPublic`). The functions that compute these cutoffs are byte-identical to those deployed during registration (commit eca79a4, 13:01 on 6 August 2026); `engine.ts` itself changed after the season only in a lint refactor whose earlier version is not available locally, and the database is the frozen October version, so this is a reconstruction rather than the output users saw. The backtest rule of `final-model.mjs` mixes, at 0.4, the percentile of v3 in the 2026 distribution with the percentile of the 2025 cutoff under the 2025 rules, and maps the mix back to the 2026 scale. Department values of the engine are kept with the author; the statistics use the released v3.'.format(
    n(E['tally'].get('method-identity', 0)), n(E['tally'].get('method-rebuilt', 0) + E['tally'].get('method-scaled', 0)),
    n(E['tally'].get('quota-applied', 0)), n(E['tally'].get('quota-unchanged-quota', 0))))
w('')
w('**Table S32a The production engine and the August rule on {} departments ({} institutions)**'.format(n(E['n']), E['institutions']))
w('')
w('| Prediction | MAE | Bias | Official ≥1 grade above | Official ≥1 grade below |')
w('|---|---:|---:|---:|---:|')
labels = {'baseline': 'Baseline of this paper', 'engineBase': 'Engine, before the quota adjustment', 'engineFinal': 'Engine, as users saw it',
          'backtestPrior': 'History side of the backtest', 'augustRule': 'Backtest rule (v3 with the backtest\'s history side)',
          'augustRuleEngine': 'Backtest rule with the engine', 'paperCombination': 'Fixed combination of this paper',
          'scoreMixEngine': 'v3 and the engine, score scale'}
for k, lab in labels.items():
    m = E['methods'][k]
    w(f'| {lab} | {m["mae"]:.2f} | {g(m["bias"])} | {pct(m["official_above_by_a_grade"])} | {pct(m["official_below_by_a_grade"])} |')
w('')
w('| Difference in MAE | Grades [interval] | Relative |')
w('|---|---|---:|')
dl = {'engine_final_minus_baseline': 'Engine minus the baseline', 'engine_base_minus_baseline': 'Engine before the quota adjustment minus the baseline',
      'august_rule_minus_backtest_prior': 'Backtest rule minus its history side', 'august_rule_engine_minus_engine_final': 'Backtest rule with the engine minus the engine',
      'paper_combination_minus_engine_final': 'Fixed combination minus the engine', 'score_mix_with_engine_minus_engine_final': 'v3 and the engine (score scale) minus the engine',
      'august_rule_engine_minus_paper_combination': 'Backtest rule with the engine minus the fixed combination'}
for k, lab in dl.items():
    d = E['differences'][k]
    w(f'| {lab} | {g(d["difference"])} {iv(d["interval"])} | {pct(d["relative"], sign=True)} |')
for k, lab in (('rules_changed', 'rules changed'), ('rules_unchanged_quota_changed', 'rules unchanged, quota changed'),
               ('rules_and_quota_unchanged', 'rules and quota unchanged')):
    d = E['by_structure'][k]
    w(f'| Backtest rule with the engine minus the engine, {lab} ({n(d["n"])}) | {g(d["august_rule_engine_minus_engine_final"])} {iv(d["interval"])} | |')
w('')
w('Note. Exploratory (plan v0.25 A). All 1,521 departments of $\\mathcal J_2$ have an engine value. The backtest rule falls back to its history side where v3 is withheld, which does not occur in $\\mathcal J_2$.')
w('')

# S32b Counterfactual simulations.
Sy, Q, Ea = A['synthetic'], A['quota2025'], A['earliest']
rows = [('Users\' preferences (rerun)', Sy['records_rerun_with_own_preferences']),
        ('Generated lists, each record\'s own length', Sy['generated_lists_own_length']),
        ('Generated lists, 55 departments', Sy['generated_lists_55']),
        ('Users\' preferences, 2025 quotas', Q['quota_2025']),
        ('Each account\'s earliest saved list', Ea['earliest_lists'])]
w('**Counterfactual simulations.** Each row reruns v3 with the current code on the evaluated records, with the production calibration, and combines it with the baseline at 0.4. Generated lists keep each record\'s grades, weight and number of eligible listings but take the eligible departments with a baseline that are nearest to the record\'s weighted score relative to the baseline, ordered by the baseline\'s level from the highest; they share {} of a record\'s actual eligible listings on average and leave {} of the mass unallocated, against {} with the users\' lists. With 2025 quotas, each department with a 2025 quota takes it ({} departments changed). The earliest list is the account\'s list in the first saved run in which it appears ({} of {} evaluated accounts changed their lists afterwards; {} listings were added and {} removed, {} and {} of them below level 30).'.format(
    pct(Sy['mean_overlap_with_real_list'], 0), pct(Sy['list_details']['ownLength']['unassignedShare']), pct(Sy['list_details']['real']['unassignedShare']),
    n(Q['departments_with_changed_quota']), n(Ea['accounts_whose_list_changed']), n(Ea['linked_accounts']),
    n(Ea['added']['listings']), n(Ea['removed']['listings']), pct(Ea['added']['levelBelow30Share']), pct(Ea['removed']['levelBelow30Share'])))
w('')
w('**Table S32b Counterfactual simulations on 1,521 departments**')
w('')
w('| Simulation | v3 covered | v3 MAE | v3 bias | Bias below level 30 | Combination minus baseline [interval] | Agreement (flagged) | Rules and quota unchanged (167) |')
w('|---|---:|---:|---:|---:|---|---|---:|')
for lab, s in rows:
    st = s.get('stable_167_gain')
    w(f'| {lab} | {n(s["covered"])} | {s["mae_alone"]:.2f} | {g(s["bias_alone"])} | {g(s["bias_below_level_30"])} | {g(s["gain"])} {iv(s["gain_interval"])} | {pct(s["agreement"])} ({n(s["flagged"])}) | {g(st) if st is not None else "—"} |')
w('')
dq = Q['decomposition']
w('Note. Exploratory (plan v0.25 B, D, E). Paired differences: users\' preferences minus generated lists {} {}; 2026 minus 2025 quotas {} {}; earliest lists minus the rerun {} {}. With the 2025-quota rerun, $S_j$ splits into a quota part (2026 minus 2025 quotas) and the rest; regressing $D_j$ on both gives slopes {} {} and {} {} on {} departments (standard deviations of the two parts {} and {} grades).'.format(
    g(Sy['own_minus_generated']['difference']), iv(Sy['own_minus_generated']['interval']),
    g(Q['difference_2026_minus_2025_quotas']['difference']), iv(Q['difference_2026_minus_2025_quotas']['interval']),
    g(Ea['earliest_minus_rerun']['difference']), iv(Ea['earliest_minus_rerun']['interval']),
    g(dq['slope_quota_part'], sign=False), iv(dq['slope_quota_part_interval']).replace('+', ''), g(dq['slope_rest'], sign=False), iv(dq['slope_rest_interval']).replace('+', ''),
    n(dq['n']), g(dq['sd_quota_part'], sign=False), g(dq['sd_rest'], sign=False)))
w('')

# S32c Placements.
P = A['placements']['preDeadline']['byMethod']
w('**Applicant-level placements.** For each record of the last run before the deadline, the placement under a set of cutoffs is the first eligible listed department whose cutoff the record\'s weighted score reaches (ties admitted); the reference is the placement under the official cutoffs, as in S20. Where a method has no value, v2 and v3 fall back to the baseline and the combination to whichever component exists; departments without a value are skipped. Fifths of the mean grade over the subjects taken are cut at quintiles of the calibrated weights, as in Table S20b. Shares are of records, unweighted; weighted shares differ by at most a few points.')
w('')
w('**Table S32c Placements against the official-cutoff reconstruction, records of noon on 8 August**')
w('')
w('| Cutoffs | Fifth | Records | Same | More favorable [interval] | Less favorable | Only the method places | Only official places | Neither |')
w('|---|---|---:|---:|---|---:|---:|---:|---:|')
names = {'baseline': 'Baseline', 'engine': 'Production engine', 'v2': 'Deployed whole-person rule (v2)', 'v3': 'v3', 'combination': 'Combination'}
for m, lab in names.items():
    t = P[m]
    for q, ql in (('all', 'All'), ('1', '1 (lowest)'), ('5', '5 (highest)')):
        x = t[q]
        r = x['records']
        ci = ''
        if q == '1':
            ci = ' ' + iv([100 * v for v in t['intervals']['earlier_lowest_fifth']], 1).replace('[', '[').replace(']', ']')
        if q == '5':
            ci = ' ' + iv([100 * v for v in t['intervals']['earlier_highest_fifth']], 1)
        w(f'| {lab if q == "all" else ""} | {ql} | {n(r)} | {pct(x["same"] / r)} | {pct(x["earlier"] / r)}{ci.replace("+", "")} | {pct(x["later"] / r)} | {pct(x["predictedOnly"] / r)} | {pct(x["officialOnly"] / r)} | {pct(x["neither"] / r)} |')
c = A['placements']['preDeadline']['combinationAgainstBaseline']['all']
w('')
w('Note. Exploratory (plan v0.25 C). Intervals are Wilson intervals for the share placed more favorably, in percent; records are not independent, so they are too narrow. Between the baseline and the combination, the placement is the same for {} of records, earlier (more favorable) under the combination for {} and later for {}. On the evaluated run the pattern is the same (combination: same {}, more favorable {}).'.format(
    pct(c['same'] / c['records']), pct(c['earlier'] / c['records']), pct(c['later'] / c['records']),
    pct(A['placements']['evaluated']['byMethod']['combination']['all']['same'] / A['placements']['evaluated']['byMethod']['combination']['all']['records']),
    pct(A['placements']['evaluated']['byMethod']['combination']['all']['earlier'] / A['placements']['evaluated']['byMethod']['combination']['all']['records'])))
w('')

# S32d Dose response.
D = H['dose_response']
w('**Table S32d The gain by kind and size of change (1,521 departments)**')
w('')
w('| Departments | Count | Combination minus baseline [interval] | Share of total gain | Agreement (flagged) |')
w('|---|---:|---|---:|---|')
for k, v in D['groups'].items():
    w(f'| {label_of(k)} | {n(v["n"])} | {g(v["gain"])} {iv(v["interval"])} | {pct(v["share_of_total_gain"])} | {pct(v["agreement"]) if v["agreement"] is not None else "—"} ({n(v["flagged"])}) |')
r = D['regression']
w('')
w('Note. Quota change is the absolute log ratio of the 2026 to the 2025 quota; the bins were fixed in plan v0.25, and the last row merges two of them for Table 5. A least-squares regression of the paired difference on the quota change and indicators of changed subjects and changed multipliers ({} departments) has intercept {} {}, slope {} per unit of quota change, and coefficients {} (subjects) and {} (multipliers).'.format(
    n(r['n']), g(r['intercept']), iv(r['intercept_interval'], 3), g(r['per_unit_dlog_q']), g(r['subjects_changed']), g(r['multipliers_changed'])))
w('')

# S32e Pooling and heterogeneity.
w('**Partial pooling and heterogeneity.** Subgroup gains are pooled with a normal–normal model whose between-cell standard deviation is estimated by restricted maximum likelihood, with each cell\'s standard error from 1,000 institution resamples. The between-institution summary of Section 6.2 uses the same estimator on each institution\'s mean paired difference: mean {}, standard deviation {}, 95% prediction interval {}; institutions\' gains correlate {} with their standard errors (DerSimonian–Laird, S30: standard deviation 0.15).'.format(
    g(H['heterogeneity']['reml_mean']), g(H['heterogeneity']['reml_tau'], sign=False), iv(H['heterogeneity']['prediction_interval']), g(H['heterogeneity']['correlation_gain_with_standard_error'])))
w('')
w('**Table S32e Raw and partially pooled subgroup gains, with the user-sampling standard deviation**')
w('')
w('| Cell | Count | Raw gain (SE) | Pooled gain | SD across half-samples |')
w('|---|---:|---|---:|---:|')
HS = A['halves']['subgroup_gain_sd']
half_key = {'north below 30': 'below_30_north', 'central below 30': 'below_30_central', 'south below 30': 'below_30_south',
            'east_and_kinmen below 30': 'below_30_east_and_kinmen', 'rules and quota unchanged': 'stable_167'}
for fam in ('region_by_level', 'structure'):
    Pf = H['pooling'][fam]
    for k, v in Pf['cells'].items():
        hs = HS.get(half_key.get(k, ''), {}).get('sd_across_halves')
        w(f'| {label_of(k)} | {n(v["n"])} | {g(v["raw"])} ({g(v["se"], sign=False)}) | {g(v["pooled"])} | {g(hs, sign=False) if hs is not None else "—"} |')
w('')
w('Note. Between-cell standard deviations: {} across the eight region-by-level cells and {} across the four kinds of change. Half-sample standard deviations come from 40 delete-half replicates with department values (the first 40 of the replicates of S26); the whole set has {}.'.format(
    g(H['pooling']['region_by_level']['tau'], sign=False), g(H['pooling']['structure']['tau'], sign=False), g(HS['all']['sd_across_halves'], 3, sign=False)))
w('')

# S32f Cutpoints, quota weighting and coverage.
C = H['cutpoints']
w('**Table S32f Low-cutoff regional gains by cutpoint, and quota-weighted results with coverage**')
w('')
w('| Group | Count (inst.) | Relative change in MAE |')
w('|---|---:|---:|')
for k, v in C.items():
    if isinstance(v, dict):
        w(f'| {label_of(k)} | {n(v["n"])} ({v["institutions"]}) | {pct(v["relative"], sign=True)} |')
w('')
w('| Group | Count | Relative, department-weighted | Relative, quota-weighted | Coverage of departments | Coverage of places |')
w('|---|---:|---:|---:|---:|---:|')
for k, v in H['quota_weighted'].items():
    w(f'| {label_of(k)} | {n(v["n"])} | {pct(v["relative"], sign=True)} | {pct(v["quota_weighted_relative"], sign=True)} | {pct(v["coverage_departments"])} | {pct(v["coverage_places"])} |')
w('')
w('Note. Coverage is the share of departments (or places) with a baseline that are in $\\mathcal J_2$, that is, that also have a released v3 value. In the south below level 30, the three private institutions with 21, 21, and 8 departments have gains of {}, {}, and {}.'.format(
    *[g(x['gain']) for x in C['south below 30 by institution'][:3]]))
w('')
w('**Table S32g The gain by level bin**')
w('')
w('| Level | Count | Combination minus baseline [interval] | Relative |')
w('|---|---:|---|---:|')
for b in C['by_level_bin']:
    w(f'| {b["level"][0]}–{b["level"][1]} | {n(b["n"])} | {g(b["gain"])} {iv(b["interval"])} | {pct(b["relative"], sign=True)} |')
w('')

# S32h Margins, shock, decision time.
M = H['margins']
w('**Margins, common shocks, and decision time.** Ex ante 90% margins are the 90th percentile of the baseline\'s 2025 backtest shortfalls (official cutoff minus prediction, in grades) on {} departments: {} overall and, by level, {}. The official cutoff exceeded the prediction plus the margin at {} of departments for the baseline and {} for the combination with the overall margin, and at {} and {} with the level margins; had the 2026 errors been 1.17 grades lower, as the reversal of the baseline\'s bias between 2025 and 2026, at {} and {}. In the 2025 backtest, the official cutoff lay above the converted prediction at {} of departments and by at least a grade at {}.'.format(
    n(M['backtest_departments']), g(M['overall_margin'], sign=False),
    '; '.join(f'{label_of(k)}: {g(v["margin"], sign=False)}' for k, v in M['by_level'].items()),
    pct(M['exceeded_overall_margin']['baseline']), pct(M['exceeded_overall_margin']['combination']),
    pct(M['exceeded_level_margin']['baseline']), pct(M['exceeded_level_margin']['combination']),
    pct(M['if_2026_errors_shifted_like_2025']['baseline']), pct(M['if_2026_errors_shifted_like_2025']['combination']),
    pct(M['backtest_2025_official_above_prediction']), pct(M['backtest_2025_official_above_by_a_grade'])))
w('')
sh = H['common_shock']
w('If every error moved by the same amount c (grades), the gain would be: ' + '; '.join(f'c = {label_of(k)}: {g(v["gain"])} ({pct(v["relative"], sign=True)})' for k, v in sh.items()) + '. Integrating the shift of the simulation alone over a normal distribution of the year\'s relative level gives an expected gain of {} (10th–90th percentile {}) for a standard deviation of 0.5 grades and {} ({}) for 0.8.'.format(
    g(H['year_shift']['sd 0.5']['expected_gain']), iv([H['year_shift']['sd 0.5']['q10'], H['year_shift']['sd 0.5']['q90']]),
    g(H['year_shift']['sd 0.8']['expected_gain']), iv([H['year_shift']['sd 0.8']['q10'], H['year_shift']['sd 0.8']['q90']])))
w('')
dt = H['decision_time']
w('Registrants completed registration on 5–8 August in shares of 10.6%, 14.2%, 33.8%, and 41.4% (UAC, 2026a). Weighting each day\'s share by the gain of that day\'s last saved run (none on 5 August) gives {} ({} of the baseline\'s MAE; {} of the evaluated run\'s gain); with each day\'s first run, {} ({}; {}).'.format(
    g(dt['last_run_of_day']['gain']), pct(-dt['last_run_of_day']['relative']), pct(dt['last_run_of_day']['share_of_evaluated_gain'], 0),
    g(dt['first_run_of_day']['gain']), pct(-dt['first_run_of_day']['relative']), pct(dt['first_run_of_day']['share_of_evaluated_gain'], 0)))
w('')

# S32i Display rules, release sets, filled.
w('**Table S32i Display rules, stricter release sets, and filling status**')
w('')
w('| Rule or set | Departments | Fallbacks | Relative change in MAE (rule) | Combination without the rule |')
w('|---|---:|---:|---:|---:|')
for rule, parts in H['display_rules'].items():
    if not isinstance(parts, dict):
        continue
    for part, v in parts.items():
        w(f'| {label_of(rule)}; {label_of(part)} | {n(v["n"])} | {n(v["fallbacks"])} | {pct(v["relative_to_baseline"], sign=True)} | {pct(v["relative_combination"], sign=True)} |')
for k, v in H['release'].items():
    if isinstance(v, dict):
        w(f'| Release set: {k} | {n(v["n"])} | — | {pct(v["relative"], sign=True)} | agreement {pct(v["agreement"])} |')
for k, v in H['filled'].items():
    w(f'| Officially {k} | {n(v["n"])} | — | {g(v["gain"])} {iv(v["interval"])} | MAE {v["mae_baseline"]:.2f} / {v["mae_v3"]:.2f} / {v["mae_combination"]:.2f} |')
w('')
w('Note. A thin low-level department has a level below 30 and fewer than three listings per place; a simulated underfilling is the simulation\'s own status. For the filling rows, the fourth column is the combination minus the baseline and the last gives the MAE of the baseline, v3, and the combination.')
w('')

# S32j Tilts.
w('**Table S32j Selection tilts**')
w('')
w('| Group | Γ | Records | Weighted share (production) | Combination minus baseline | Agreement (flagged) | v3 bias below level 30 |')
w('|---|---:|---:|---|---:|---|---:|')
for t in A['tilt']:
    w(f'| {t["group"]} | {t["gamma"]} | {n(t["records"])} | {pct(t["weighted_share"])} ({pct(t["production_share"])}) | {g(t["gain"])} | {pct(t["direction_agreement"])} ({n(t["flagged"])}) | {g(t["bias_below_level_30"])} |')
w('')
w('Note. Exploratory (plan v0.25 F). Γ multiplies the starting weight of records in the group (above the median share of private institutions, of departments below level 30, or of list length) before raking to the production margins; all calibrations converged. S27h gives Γ = 0.8 and 1.25.')
w('')

# S32k Sampling variance, plan v0.18, frame centering, other.
V = A['halves']
w('**Sampling variance by department.** Across 40 delete-half replicates, the median sampling standard deviation of a department\'s v3 is {} grades ({} departments with at least 20 replicate values). By listings, the mean sampling variance as a share of v3\'s mean squared error is: {}. With 200 with-replacement resamples, the result that plan v0.18 specified, the official cutoff lay inside the department\'s 90% interval for {} of {} departments (median width {} grades; the replicates\' v3 MAE has median {}, against 1.82 for the full sample).'.format(
    g(V['median_sampling_sd_v3'], sign=False), n(V['departments_with_psi']),
    '; '.join(f'{b["listings"][0]}–{b["listings"][1] if b["listings"][1] else ""}: {pct(b["sampling_share"], 0)} of {n(b["n"])}' for b in V['by_listings']),
    pct(H['plan_v018']['official_inside_90']), n(H['plan_v018']['departments']), g(H['plan_v018']['median_width_90_grades'], sign=False),
    g(H['plan_v018']['replicate_v3_mae_median'], sign=False)))
w('')
w('**Table S32k Raw and self-centered gains of earlier frame, scaling, and truncation reruns**')
w('')
w('| Rerun | Mean S | Raw gain [interval] | Centered gain [interval] | Official ≥1 grade above, raw / centered |')
w('|---|---:|---|---|---|')
for k, v in A['centered'].items():
    if v is None:
        continue
    w(f'| {label_of(k)} | {g(v["mean_S"])} | {g(v["raw_gain"])} {iv(v["raw_interval"])} | {g(v["centered_gain"])} {iv(v["centered_interval"])} | {pct(v["raw_official_above"])} / {pct(v["centered_official_above"])} |')
w('')
w('Note. Exploratory (plan v0.25 G4). Centering subtracts the rerun\'s mean simulated departure on $\\mathcal J_2$, which needs no outcome. The reruns are those of S27 and S28.')
w('')
Enc = H['encompassing']
NE = A['neff']
R0 = A['returners']
NH = H['no_history']
PR = H['practical']
w('**Other checks.** Encompassing tests in both directions (Harvey et al., 1998), with institution-clustered variance: that the baseline encompasses v3, $t={:.2f}$; that v3 encompasses the baseline, $t={:.2f}$. The planned regression of $D$ on $S$ through the origin has slope {} ($t={:.1f}$). The Kish effective sample size of a department\'s eligible listers has median {} on $\\mathcal J_2$ (10th percentile {}), correlates {} with the listing count by rank, and orders v3\'s absolute errors as well as listings do (Spearman {} against {}). Records last updated before the deadline took {} subjects on average and had a mean grade of {} (weighted {}), against {} and {} (weighted {}) for the others; plan v0.24 had specified these comparisons, but the earlier computation counted subjects not taken, which carry negative values, so they were not reported (S15). For the {} departments without a previous cutoff, v3 alone has MAE {} (bias {}); a synthetic value, the institution\'s median level times the multiplier total, has MAE {}, and mixing it with v3 at 0.4 and 0.6 gives {} and {} (exploratory, fitted after the outcomes). The MAE-minimizing weight on $\\mathcal J_2$ is {}; listing-weighted MAE falls by {}; the 707 departments where the baseline missed by less than a grade lose {} of the total gain, and those where it missed by 1–2, 2–4, and at least 4 grades supply {}, {}, and {}.'.format(
    Enc['hln_baseline_encompasses_v3']['t'], Enc['hln_v3_encompasses_baseline']['t'], g(Enc['slope_through_origin'], sign=False), Enc['t_through_origin'],
    g(NE['summary']['median'], 0, sign=False), g(NE['summary']['p10'], 0, sign=False), g(NE['spearman_neff_listings'], sign=False),
    g(NE['spearman_neff_abs_error_v3']), g(NE['spearman_listings_abs_error_v3']),
    g(R0['before']['subjects']['unweighted'], 1, sign=False), g(R0['before']['meanNormalizedGrade']['unweighted'], 1, sign=False), g(R0['before']['meanNormalizedGrade']['weighted'], 1, sign=False),
    g(R0['afterOrUnknown']['subjects']['unweighted'], 1, sign=False), g(R0['afterOrUnknown']['meanNormalizedGrade']['unweighted'], 1, sign=False), g(R0['afterOrUnknown']['meanNormalizedGrade']['weighted'], 1, sign=False),
    n(NH['n']), g(NH['mae_v3'], sign=False), g(NH['bias_v3']), g(NH['mae_synthetic'], sign=False), g(NH['mae_mix_0.4'], sign=False), g(NH['mae_mix_0.6'], sign=False),
    g(PR['mae_optimal_weight'][0], 3, sign=False), pct(-PR['listing_weighted_mae']['relative']),
    pct(-PR['contribution_by_baseline_error']['0-1']['share_of_total_gain']), pct(PR['contribution_by_baseline_error']['1-2']['share_of_total_gain']),
    pct(PR['contribution_by_baseline_error']['2-4']['share_of_total_gain']), pct(PR['contribution_by_baseline_error']['4-inf']['share_of_total_gain'])))
w('')
w('**Content hashes of the saved runs.** For a later export to be compared with the deleted one, each run\'s content is hashed without identifiers or times: each record\'s grades (keys sorted), preferences, and mirror flag as canonical JSON, the lines sorted and joined. ' + '; '.join(f'{h["runId"]}: {h["records"]:,} documents, {h["contentSHA256"][:16]}…' for h in A['run_content_hashes']) + '. The full hashes are in `data/author-checks-round6.json`.')
w('')
output_path('s32.md').write_text('\n'.join(out) + '\n')
print('\n'.join(out)[:2000])
