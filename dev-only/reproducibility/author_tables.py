"""Tables of the record-level checks (Table 7 of the manuscript, v0.26, and Supplement S20b, S24-S28) from the released aggregates.

Reads data/author-checks.json, data/author-stats.json and the released department file, and writes the tables as
markdown to out/author-tables.md, rounding once, from full precision. The evaluated run's row of Table 7 uses the
controlled tier's department values, like Tables 2-6; the other rows use the reruns' aggregates. The output keys T6
and T5 keep the numbering of v0.24: T6 is Table 7 of v0.26, and T5 is an earlier form of Table 6 and Supplement
Table S30g (v0.26 builds Tables 5 and 6 with seventh_tables.py).

Usage: python3 author_tables.py
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, common_rows, load_rows, output_path  # noqa: E402
from decision_checks import LAMBDA, mae_difference  # noqa: E402

TW = timezone(timedelta(hours=8))
MINUS = '−'


def num(x, d=2):
    return f'{x:,.{d}f}'.replace('-', MINUS)


def sg(x, d=2):
    return ('+' if x >= 0 else MINUS) + f'{abs(x):.{d}f}'


def pct(x, d=1):
    return f'{100 * x:.{d}f}%'


def spct(x, d=1):
    return ('+' if x >= 0 else MINUS) + f'{100 * abs(x):.{d}f}'


def ci(c, d=2):
    return f"{sg(c['difference'], d)} [{sg(c['interval'][0], d)}, {sg(c['interval'][1], d)}]"


def pci(c):
    return f"{spct(c['difference'])} [{spct(c['interval'][0])}, {spct(c['interval'][1])}]"


def when(iso):
    t = datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone(TW)
    return f'{t.day} Aug {t:%H:%M}'


def table(head, align, rows):
    return '\n'.join(['| ' + ' | '.join(head) + ' |', '|' + '|'.join(align) + '|'] + ['| ' + ' | '.join(r) + ' |' for r in rows])


def main():
    data = PAPER / 'data'
    checks = json.loads((data / 'author-checks.json').read_text())
    C = checks['sections']
    S = json.loads((data / 'author-stats.json').read_text())['groups']
    runs = {r['label']: r for r in C['runs']['summary']}
    L = S['runs']['labels']
    out, key = {}, {}

    # ------------------------------------------------------------ Table 7 (key T6): data vintage against method version
    rows = load_rows()
    j2 = common_rows(rows, ('v3', 'baseline'))
    base = lambda r: r['baseline']
    released = {}
    for m in ('v2', 'fractional', 'v3'):
        mix = lambda r, m=m: LAMBDA * r[m] + (1 - LAMBDA) * r['baseline'] if r[m] is not None else r['baseline']
        released[m] = mae_difference(j2, mix, base)
    V = S['vintage']['labels']
    t6 = []
    for lab, name in (('run-ast_20260808T035958Z', 'Saved run, 8 Aug 12:01, last before the deadline'),
                      ('deadline-reconstructed', 'Deadline reconstruction')):
        n = runs[lab]['counts']['effective']
        t6.append([name, f'{n:,}', ci(V[lab]['v2']['combination_minus_baseline']),
                   ci(V[lab]['fractional']['combination_minus_baseline']), ci(L[lab]['combination_minus_baseline'])])
    t6.append(['Evaluated run, 15 Aug 23:01 (released values)', '4,627', ci(released['v2']), ci(released['fractional']), ci(released['v3'])])
    out['T6'] = table(['Records saved', 'Records', 'Whole-person rule (v2)', 'Divisible mass (Fractional)', 'Divisible mass with interpolation (v3)'],
                      ['---', '---:', '---', '---', '---'], t6)
    key['table6'] = {'released': {m: {'difference': v['difference'], 'interval': v['interval'], 'relative': v['relative']} for m, v in released.items()}}

    # ------------------------------------------------------------ key T5: by level and, below 30, by region (an earlier form of Table 6)
    eq = json.loads((data / 'revision-checks.json').read_text())['equity']
    t5 = []
    for b, name in (('0-30', 'Level 0–30'), ('30-40', 'Level 30–40'), ('40-45', 'Level 40–45'), ('45-50', 'Level 45–50'), ('50-61', 'Level 50–60'),
                    ('north_and_central|below_30', 'Level 0–30, north and central'),
                    ('south_east_and_kinmen|below_30', 'Level 0–30, south, east, and Kinmen')):
        v = eq['levels'][b] if b in eq['levels'] else eq['region_by_level'][b]
        t5.append([name, f"{v['n']:,}", sg(v['bias_v3']), sg(v['bias_baseline']),
                   f"{num(v['mae_baseline'])} / {num(v['mae_v3'])} / {num(v['mae_combination'])}",
                   f"{sg(v['gain'])} [{sg(v['interval'][0])}, {sg(v['interval'][1])}]",
                   f"{pct(v['above_baseline'])} → {pct(v['above_combination'])}"])
    out['T5'] = table(['Departments', 'Count', 'v3 bias', 'Hist. bias', 'MAE: Hist. / v3 / Comb.', 'Combination minus historical',
                       'Official ≥1 grade above: Hist. → Comb.'], ['---', '---:', '---:', '---:', '---', '---', '---'], t5)

    # ------------------------------------------------------------ S24a runs in the export
    tim = {r['runId']: r for r in C['timing']['byRun']}
    t = []
    for lab, r in runs.items():
        if not lab.startswith('run-') or lab.endswith('no-zero-cleaning'):
            continue
        rid = r['run']['runId']
        c = r['counts']
        t.append([f'`{rid}`', when(r['run']['completedAt']), r['run']['algorithmVersion'].replace('ast-da-', ''), f"{c['documents']:,}",
                  str(c['mirrorCopies']), str(c['zeroCleaningRecords']), str(c['mergedAway']), f"{c['effective']:,}",
                  f"{tim[rid]['updatedAfterDeadline']:,}"])
    out['S24a'] = table(['Run', 'Completed (Taiwan)', 'Version at the time', 'Documents', 'Mirror copies', 'Zero grades reclassified',
                         'Merged as identical', 'Records used', 'Last updated after the deadline'],
                        ['---', '---', '---', '---:', '---:', '---:', '---:', '---:', '---:'], t)

    # ------------------------------------------------------------ S24b reproduction
    rep = C['reproduce']
    t = []
    for k, name in (('v1', 'v1'), ('v2', 'v2'), ('fractional', 'Fractional'), ('v3', 'v3')):
        c = rep['comparison'][k]
        t.append([name, f"{c['both']:,}", str(c['availabilityDiffers']), f"{c['identical']:,}", num(c['maxAbsDifference']),
                  f"{c['j2Common']:,}", f"{num(c['j2MAEReconstructed'], 3)} / {num(c['j2MAEFrozen'], 3)}"])
    out['S24b'] = table(['Method', 'Values in both', 'Availability differs', 'Identical', 'Largest difference', '$\\mathcal J_2$ departments',
                         'MAE: rerun / frozen'], ['---', '---:', '---:', '---:', '---:', '---:', '---'], t)
    key['reproduce'] = {'raking': rep['raking'], 'records': rep['records']}
    ties = C['ties']
    key['ties'] = {'differing': [min(r['differFromFrozen'] for r in ties['results']) if 'differFromFrozen' in ties['results'][0] else None],
                   'predMAE': ties['predMAE'], 'mixMinusBaseline': ties['mixMinusBaseline'], 'directionAgreement': ties['directionAgreement']}

    # ------------------------------------------------------------ S25a, S25b panel and kinds of change
    p = C['timing']['panel']
    b = p['byUpdate']
    t = [[name, f"{b[k]['identical']:,}", f"{b[k]['changed']:,}", f"{b[k]['new']:,}", f"{sum(b[k].values()):,}"]
         for k, name in (('beforeDeadline', 'Before the deadline'), ('afterDeadline', 'After the deadline'))]
    t.append(['Total', f"{p['identicalToPreDeadline']:,}", f"{p['changedSincePreDeadline']:,}", f"{p['newSincePreDeadline']:,}", f"{p['evaluatedRecords']:,}"])
    out['S25a'] = table(['Last updated', 'Identical', 'Changed', 'New', 'Total'], ['---', '---:', '---:', '---:', '---:'], t)
    ch = C['changes']['byUpdate']
    t = []
    for k, name in (('beforeDeadline', 'Before the deadline'), ('afterDeadline', 'After the deadline')):
        c = ch[k]
        t.append([name, str(c['gradesOnly']), str(c['preferencesOnly']), str(c['both']), str(c['preferenceSetUnchanged']),
                  f"{c['listLengthChange']['lengthened']} / {c['listLengthChange']['shortened']}"])
    out['S25b'] = table(['Last updated', 'Grades only', 'Preferences only', 'Both', 'Same departments reordered',
                         'Lists lengthened / shortened'], ['---', '---:', '---:', '---:', '---:', '---'], t)
    key['changes'] = ch

    # ------------------------------------------------------------ S25c reruns on each input
    order = ['run-ast_20260805T175904Z', 'run-ast_20260805T175904Z-no-zero-cleaning', 'run-ast_20260806T120005Z',
             'run-ast_20260806T120005Z-no-zero-cleaning', 'run-ast_20260807T022008Z', 'run-ast_20260807T120012Z',
             'run-ast_20260808T035958Z', 'run-ast_20260808T095000Z', 'run-ast_20260813T012242Z', 'run-ast_20260815T150000Z',
             'deadline-reconstructed', 'evaluated-pre-deadline-states', 'evaluated-updated-before-deadline']
    names = {'deadline-reconstructed': 'Deadline reconstruction', 'evaluated-pre-deadline-states': 'Evaluated records in their last pre-deadline state',
             'evaluated-updated-before-deadline': 'Evaluated records last updated before the deadline'}
    t = []
    for lab in order:
        r, s = runs[lab], L[lab]
        if lab in names:
            name = names[lab]
        else:
            name = ('Evaluated run, ' if lab.endswith('150000Z') else 'Saved run, ') + when(r['run']['completedAt'])
            if lab.endswith('no-zero-cleaning'):
                name += ', zero grades kept'
        t.append([name, f"{r['counts']['effective']:,}", f"{r['raking']['nEff']:,.0f}", f"{s['covered']:,}", num(s['prediction']['mae']),
                  ci(s['combination_minus_baseline']), spct(s['combination_minus_baseline']['relative']) + '%',
                  pci(s['above_share_difference']), f"{pct(s['flags_delta1']['direction_agreement'])} ({s['flags_delta1']['flagged']:,})",
                  num(s['optimal_weight']['squared_error'])])
    out['S25c'] = table(['Input', 'Records', 'Kish $n_{\\mathrm{eff}}$', 'Covered', 'v3 MAE', 'Combination minus historical', 'Relative',
                         'Official ≥1 grade above, change (points)', 'Agreement (flagged)', 'Best weight'],
                        ['---', '---:', '---:', '---:', '---:', '---', '---:', '---', '---', '---:'], t)
    key['runs'] = {lab: {'records': runs[lab]['counts']['effective'], 'nEff': runs[lab]['raking']['nEff'],
                         'gain': L[lab]['combination_minus_baseline'], 'above': L[lab]['above_share_difference'],
                         'above_share': L[lab]['combination']['official_at_least_one_grade_above'],
                         'agreement': L[lab]['flags_delta1'], 'mae': L[lab]['prediction']['mae'],
                         'weight': L[lab]['optimal_weight']} for lab in order}

    # ------------------------------------------------------------ S25d rule change, S25e flags (detail group)
    D = S['detail']['labels']
    lab_names = (('run-ast_20260808T035958Z', 'Last pre-deadline run'), ('deadline-reconstructed', 'Deadline reconstruction'),
                 ('evaluated-main', 'Evaluated run'))
    cell = lambda g: f"{g['n']:,}: {ci(g['mix_minus_baseline'])}"
    t = []
    for lab, name in lab_names:
        d = D[lab]
        pr = d['permutation_reference']
        t.append([name, cell(d['rule_change']['unchanged']), cell(d['rule_change']['multipliers']), cell(d['rule_change']['subjects']),
                  cell(d['structure_unchanged_quota_identical']),
                  f"{pct(pr['mean'])} [{pct(pr['interval'][0])}, {pct(pr['interval'][1])}]"])
    out['S25d'] = table(['Input', 'Unchanged rules', 'Multipliers changed', 'Subjects changed', 'Unchanged rules and quota', 'Permutation reference'],
                        ['---'] * 6, t)
    t = []
    for lab, name in lab_names:
        f = D[lab]['flags_delta1']
        t.append([name, f"{f['flagged']:,}", pct(f['direction_agreement']), pct(f['moved_by_threshold_in_flagged_direction']),
                  pct(f['hot_precision']), pct(f['cold_precision']), num(f['gerrity_skill_score'])])
    out['S25e'] = table(['Input', 'Flagged', 'Agreement', 'Moved ≥1 grade in flagged direction', 'Upward precision', 'Downward precision',
                         'Gerrity skill score'], ['---', '---:', '---:', '---:', '---:', '---:', '---:'], t)

    # ------------------------------------------------------------ S26a uncertainty from the sample of candidates
    hs, hn, bb, bs = C['halfsamples'], C['halfsamples-ast_20260808T035958Z'], C['bayesboot'], C['bootstrap']
    t = [['Half-samples without replacement, evaluated run', f"{hs['draws']} ({hs['records']:,} records)", num(hs['mean']['mixMinusBaseline'], 3),
          num(hs['sd']['mixMinusBaseline'], 3), '—', f"{hs['share']['mixBetterThanBaseline'] * hs['draws']:.0f} of {hs['draws']}"],
         ['Half-samples without replacement, last pre-deadline run', f"{hn['draws']} ({hn['records']:,} records)", num(hn['mean']['mixMinusBaseline'], 3),
          num(hn['sd']['mixMinusBaseline'], 3), '—', f"{hn['share']['mixBetterThanBaseline'] * hn['draws']:.0f} of {hn['draws']}"],
         ['Resampling with replacement (plan v0.18)', f"{bs['B']}", num(bs['mixMinusBaseline']['mean'], 3), '—',
          f"[{num(bs['mixMinusBaseline']['p025'], 3)}, {num(bs['mixMinusBaseline']['p975'], 3)}]", f"{bs['shareMixBetterThanBaseline'] * bs['B']:.0f} of {bs['B']}"],
         ['Bayesian bootstrap (exponential weights before calibration)', f"{bb['B']}", num(bb['mixMinusBaseline']['mean'], 3), '—',
          f"[{num(bb['mixMinusBaseline']['p025'], 3)}, {num(bb['mixMinusBaseline']['p975'], 3)}]", f"{bb['shareMixBetterThanBaseline'] * bb['B']:.0f} of {bb['B']}"]]
    out['S26a'] = table(['Procedure', 'Draws', 'Mean gain', 'SD across draws', '2.5th–97.5th percentile', 'Combination better'],
                        ['---', '---', '---:', '---:', '---', '---'], t)
    key['uncertainty'] = {'half_eval': hs, 'half_noon': hn, 'bayes': bb, 'boot': bs}
    # Institution composition and the sample of candidates combined: normal approximation with the cluster interval's
    # standard deviation (its width over 2 x 1.96) and the half-sample standard deviation, added in variance.
    for name, lab, half in (('evaluated', 'run-ast_20260815T150000Z', hs), ('pre_deadline', 'run-ast_20260808T035958Z', hn)):
        g = L[lab]['combination_minus_baseline']
        sd_cluster = (g['interval'][1] - g['interval'][0]) / (2 * 1.959964)
        sd = (sd_cluster ** 2 + half['sd']['mixMinusBaseline'] ** 2) ** 0.5
        key['uncertainty'][f'combined_{name}'] = {'difference': g['difference'], 'sd_cluster': sd_cluster,
                                                  'sd_candidates': half['sd']['mixMinusBaseline'], 'sd': sd,
                                                  'interval': [g['difference'] - 1.959964 * sd, g['difference'] + 1.959964 * sd]}

    # ------------------------------------------------------------ S26b learning curve
    cv = C['curve']
    t = []
    for k in sorted(cv['levels'], key=int):
        c = cv['levels'][k]
        g = c['mixMinusBaseline']
        t.append([f'{int(k)}/8', f"{c['records']:,}", f"{c['nEff']['mean']:,.0f}", f"{num(c['predMAE']['mean'])} ({num(c['predMAE']['sd'])})",
                  f"{sg(g['mean'], 3)} ({num(g['sd'], 3)})", f"[{sg(g['min'], 3)}, {sg(g['max'], 3)}]",
                  pct(c['mixOfficialAboveShare']['mean']), pct(c['directionAgreement']['mean']), sg(c['meanS']['mean'])])
    ev = runs['run-ast_20260815T150000Z']
    t.append(['8/8 (all)', '4,627', f"{ev['raking']['nEff']:,.0f}", num(L['run-ast_20260815T150000Z']['prediction']['mae']),
              sg(L['run-ast_20260815T150000Z']['combination_minus_baseline']['difference'], 3), '—',
              pct(L['run-ast_20260815T150000Z']['combination']['official_at_least_one_grade_above']),
              pct(L['run-ast_20260815T150000Z']['flags_delta1']['direction_agreement']), sg(L['run-ast_20260815T150000Z']['mean_S'])])
    out['S26b'] = table(['Share of records', 'Records', 'Kish $n_{\\mathrm{eff}}$ (mean)', 'v3 MAE: mean (SD)', 'Gain: mean (SD)', 'Gain: range',
                         'Official ≥1 grade above', 'Agreement', 'Mean $S$'],
                        ['---', '---:', '---:', '---', '---', '---', '---:', '---:', '---:'], t)
    key['curve'] = cv['levels']

    # ------------------------------------------------------------ S27a calibration settings
    VV = {v['label']: v for v in C['variants']['variants']}
    SV = S['variants']['labels']
    rows27 = (('main', 'Three bands (production)'), ('collapsed-ten-grade', 'Ten-grade cells, merged'),
              ('collapsed-single-grade', 'Single-grade cells, merged'), ('bounded-0.2-10', 'Three bands, weights bounded to 0.2–10× mean'),
              ('bounded-0.2-5', 'Three bands, weights bounded to 0.2–5× mean'),
              ('exclude-no-eligible', 'Three bands, without the 18 records lacking an eligible preference'),
              ('dedupe-grades', 'Three bands, one record per vector of grades'),
              ('registrant-scaled', 'Three bands, rescaled to 33,071'), ('uniform-calibrated-total', 'Equal weights, total 35,912'),
              ('uniform-registrants', 'Equal weights, total 33,071'))
    dd = C['dedupe']
    t = []
    for lab, name in rows27:
        s = SV[f'variant-{lab}']
        if lab == 'dedupe-grades':
            v = {'records': dd['kept'], 'totalWeight': dd['raking']['sumW'], 'nEff': dd['raking']['nEff'], 'raking': dd['raking']}
        else:
            v = VV[lab]
        rk = v.get('raking') or {}
        conv = '—'
        if rk:
            conv = 'yes' if rk.get('converged') else 'no'
            if 'maxRelErr' in rk:
                conv += f" ({pct(rk['maxRelErr'], 2)})"
        cells = rk.get('cells') or (42 if lab.startswith(('bounded', 'dedupe')) else None)
        t.append([name, f"{v['records']:,}", str(cells) if cells else '—', conv, f"{v['totalWeight']:,.0f}", f"{v['nEff']:,.0f}",
                  num(rk['max'], 1) if rk.get('max') else '—', num(s['prediction']['mae']), sg(s['mean_S']),
                  ci(s['combination_minus_baseline']), pct(s['flags_delta1']['direction_agreement'])])
    out['S27a'] = table(['Setting', 'Records', 'Cells', 'Converged (largest adjustment, last cycle)', 'Total weight', 'Kish $n_{\\mathrm{eff}}$', 'Max. weight',
                         'v3 MAE', 'Mean $S$', 'Combination minus historical', 'Agreement'],
                        ['---', '---:', '---:', '---', '---:', '---:', '---:', '---:', '---:', '---', '---:'], t)
    key['variants'] = {lab: SV[f'variant-{lab}'] for lab, _ in rows27}
    key['dedupe'] = dd

    # ------------------------------------------------------------ S27b fit to the official grade distributions
    fit = C['fit']['result']
    t = [[name, pct(fit[k]['meanGradeTAE']), num(fit[k]['meanAbsWithinBandDifference']), sg(fit[k]['meanWithinBandDifference'])]
         for k, name in (('three-band (production)', 'Three bands (production)'), ('collapsed ten-grade', 'Ten-grade cells, merged'),
                         ('collapsed single-grade', 'Single-grade cells, merged'), ('bounded 0.2-5', 'Bounded 0.2–5×'),
                         ('bounded 0.2-10', 'Bounded 0.2–10×'), ('uniform at calibrated total', 'Equal weights'))]
    out['S27b'] = table(['Weighting', 'Mean per-grade total absolute error', 'Mean absolute within-band difference (grades)',
                         'Mean within-band difference (grades)'], ['---', '---:', '---:', '---:'], t)

    # ------------------------------------------------------------ S27c bias by level
    LV = S['levels']['labels']
    lv_rows = (('evaluated-main', 'Three bands (production)'), ('run-ast_20260808T035958Z', 'Last pre-deadline run'),
               ('variant-collapsed-ten-grade', 'Ten-grade cells, merged'), ('variant-collapsed-single-grade', 'Single-grade cells, merged'),
               ('variant-bounded-0.2-10', 'Bounded 0.2–10×'), ('variant-registrant-scaled', 'Rescaled to 33,071'),
               ('variant-uniform-calibrated-total', 'Equal weights'), ('variant-truncate-40', 'Lists cut to 40'),
               ('variant-truncate-20', 'Lists cut to 20'), ('trs-0', 'Integer population (first draw)'))
    bands = ('0-30', '30-40', '40-45', '45-50', '50-61')
    out['S27c'] = table(['Setting', '0–30', '30–40', '40–45', '45–50', '50–60'], ['---'] + ['---:'] * 5,
                        [[name] + [sg(LV[lab][b]['bias']) for b in bands] for lab, name in lv_rows])
    key['levels'] = LV

    # ------------------------------------------------------------ S27d, S27e joint distribution
    J = C['joint']
    t = []
    for w, name in (('calibrated', 'Calibrated'), ('uniform', 'Uniform')):
        s = J['comboSummary'][w]
        t.append([name, str(s['combinations']), num(s['medianAbsLogRatioAll'], 3)] +
                 [f"{num(s['medianAbsLogRatioAbove'][q], 3)} ({sg(s['medianLogRatioAbove'][q], 3)})" for q in ('0.5', '0.75', '0.9', '0.95')])
    out['S27d'] = table(['Weighting', 'Combinations', 'All holders', 'Above official median', 'Above 75th percentile', 'Above 90th percentile',
                         'Above 95th percentile'], ['---', '---:', '---:', '---:', '---:', '---:', '---:'], t)
    t = []
    for w, name in (('calibrated', 'Calibrated'), ('uniform', 'Uniform')):
        s = J['departmentSummary'][w]
        lr = s['logRatio']
        t.append([name, f"{s['departments']} ({s['schools']})", f"{sg(lr['p25'])} / {sg(lr['median'])} / {sg(lr['p75'])}", num(lr['meanAbs'], 3),
                  sg(s['spearmanWithError']), sg(s['spearmanWithS']), sg(s['spearmanWithD']),
                  f"{s['meanErrorByLogRatioSign']['over']['n']}: {sg(s['meanErrorByLogRatioSign']['over']['meanError'])} / "
                  f"{s['meanErrorByLogRatioSign']['under']['n']}: {sg(s['meanErrorByLogRatioSign']['under']['meanError'])}"])
    out['S27e'] = table(['Weighting', 'Departments (institutions)', 'Log ratio: 25th / 50th / 75th percentile', 'Mean absolute log ratio',
                         'Spearman with v3 error', 'Spearman with $S$', 'Spearman with $D$', 'Mean v3 error: more / fewer than official'],
                        ['---', '---', '---', '---:', '---:', '---:', '---:', '---'], t)
    JP = C['jointpairs']
    t = []
    for band, name in (('0-30', '0–30'), ('30-40', '30–40'), ('40-45', '40–45'), ('45-50', '45–50'), ('50-60', '50–60')):
        lv = JP['levels'][band]
        t.append([name, str(lv['departments']), pct(lv['shareOfJ2Band'], 0), num(lv['medianGradesFor5Percent']),
                  num(lv['meanAbsTotal'], 3), num(lv['meanAbsComposition'], 3)])
    out['S27f'] = table(['Historical level', 'Departments', 'Share of the level in $\\mathcal J_2$', 'Grades that move the official count by 5%',
                         'Mean absolute count error of v3', 'Mean absolute composition error'], ['---', '---:', '---:', '---:', '---:', '---:'], t)
    key['jointpairs'] = JP
    key['joint'] = J['departmentSummary']

    # ------------------------------------------------------------ S27g selection: coverage, bounds and tilts
    PA = C['participation']
    cov = PA['coverage']
    t = []
    for subj, bandsv in cov.items():
        cells = []
        for bnd in bandsv:
            cells.append(pct(bnd['coverage']) if isinstance(bnd.get('coverage'), float) else '<5 records')
        t.append([f'`{subj}`'] + cells)
    out['S27g'] = table(['Subject', 'Grades 0–19', 'Grades 20–39', 'Grades 40–60'], ['---', '---:', '---:', '---:'], t)
    TL = C['tilt']['results']
    t = [['Frame: highest-ranked 2,840 units removed, not recalibrated', '—', sg(PA['bounds']['top']['j2']['meanS']), num(PA['bounds']['top']['j2']['predMAE']),
          sg(PA['bounds']['top']['j2']['mixMinusBaseline'], 3), pct(PA['bounds']['top']['j2']['mixOfficialAboveShare']),
          pct(PA['bounds']['top']['j2']['directionAgreement'])],
         ['Frame: lowest-ranked 2,840 units removed, not recalibrated', '—', sg(PA['bounds']['bottom']['j2']['meanS']), num(PA['bounds']['bottom']['j2']['predMAE']),
          sg(PA['bounds']['bottom']['j2']['mixMinusBaseline'], 3), pct(PA['bounds']['bottom']['j2']['mixOfficialAboveShare']),
          pct(PA['bounds']['bottom']['j2']['directionAgreement'])]]
    gnames = {'private-leaning': 'Records listing mostly private institutions', 'long-lists': 'Records with long lists'}
    for r in TL:
        t.append([f"Tilt: {gnames.get(r['group'], r['group']).lower()}, Γ = {r['gamma']:g}", f"{pct(r['weightedShare'])} (from {pct(r['productionShare'])})",
                  sg(r['j2']['meanS']), num(r['j2']['predMAE']), sg(r['j2']['mixMinusBaseline'], 3), pct(r['j2']['mixOfficialAboveShare']),
                  pct(r['j2']['directionAgreement'])])
    out['S27h'] = table(['Scenario', 'Weighted share of the group', 'Mean $S$', 'v3 MAE', 'Combination minus historical',
                         'Official ≥1 grade above combination', 'Agreement'],
                        ['---', '---', '---:', '---:', '---:', '---:', '---:'], t)
    key['participation'] = {'weightedMeanListed': PA['weightedMeanListed'], 'weightedMeanEligible': PA['weightedMeanEligible'],
                            'bounds': PA['bounds'], 'coverage': cov}
    key['tilt'] = TL

    # ------------------------------------------------------------ S28a integer populations
    TR = S['trs']['labels']
    t = []
    for i, r in enumerate(C['trs']['results']):
        s = TR[f'trs-{i}']
        t.append([str(r['seed']), f"{r['persons']:,}", num(s['prediction']['mae']), sg(s['mean_S']), sg(s['combination_minus_baseline']['difference'], 3),
                  pct(s['flags_delta1']['direction_agreement']), f"{num(r['meanAbsDiffFromFractional'], 3)} / {num(r['meanAbsDiffFromV3'], 3)}"])
    fr = SV['fractional-main']
    t.append(['Fractional (divisible mass)', '35,912 units', num(fr['prediction']['mae']), sg(fr['mean_S']), sg(fr['combination_minus_baseline']['difference'], 3),
              pct(fr['flags_delta1']['direction_agreement']), '—'])
    out['S28a'] = table(['Draw (seed)', 'Persons', 'MAE', 'Mean $S$', 'Combination minus historical', 'Agreement',
                         'Mean absolute difference from Fractional / v3'], ['---', '---:', '---:', '---:', '---:', '---:', '---'], t)
    key['trs'] = {'mae': [TR[f'trs-{i}']['prediction']['mae'] for i in range(10)],
                  'gain': [TR[f'trs-{i}']['combination_minus_baseline']['difference'] for i in range(10)],
                  'agreement': [TR[f'trs-{i}']['flags_delta1']['direction_agreement'] for i in range(10)],
                  'meanS': [TR[f'trs-{i}']['mean_S'] for i in range(10)],
                  'diffFractional': [r['meanAbsDiffFromFractional'] for r in C['trs']['results']],
                  'fractional': {'mae': fr['prediction']['mae'], 'gain': fr['combination_minus_baseline']['difference'], 'meanS': fr['mean_S']}}

    # ------------------------------------------------------------ S28b truncated lists
    t = []
    for k in (5, 10, 20, 40):
        s, v = SV[f'variant-truncate-{k}'], VV[f'truncate-{k}']
        t.append([f'First {k}', num(v['meanListed'], 1), f"{s['covered']:,}", num(s['prediction']['mae']), sg(s['mean_S']),
                  ci(s['combination_minus_baseline']), pct(s['flags_delta1']['direction_agreement'])])
    m = SV['variant-main']
    t.append(['All', num(C['reproduce']['records']['meanListedPreferences'], 1), f"{m['covered']:,}", num(m['prediction']['mae']), sg(m['mean_S']),
              ci(m['combination_minus_baseline']), pct(m['flags_delta1']['direction_agreement'])])
    out['S28b'] = table(['Preferences kept', 'Mean listed', 'Covered', 'v3 MAE', 'Mean $S$', 'Combination minus historical', 'Agreement'],
                        ['---', '---:', '---:', '---:', '---:', '---', '---:'], t)

    # ------------------------------------------------------------ S28c subsamples
    SS = S['subsamples']['labels']
    t = []
    for share in (25, 50, 75):
        for d in range(5):
            s = SS[f'subsample-{share}-{d}']
            res = [r for r in C['subsamples']['results'] if r.get('label') == f'subsample-{share}-{d}']
            records = res[0]['records'] if res and 'records' in res[0] else round(4627 * share / 100)
            t.append([f'{share}%', str(d + 1), f'{records:,}', f"{s['covered']:,}", num(s['prediction']['mae']),
                      sg(s['combination_minus_baseline']['difference'], 3), pct(s['flags_delta1']['direction_agreement'])])
    out['S28c'] = table(['Share of records', 'Draw', 'Records', 'Covered', 'v3 MAE', 'Combination minus historical', 'Agreement'],
                        ['---', '---:', '---:', '---:', '---:', '---:', '---:'], t)

    # ------------------------------------------------------------ S20b placements by quintile
    PL = C['placements']['report']
    t = []
    for lab, rule, name in (('evaluated', 'divisible', 'Evaluated run, divisible mass'), ('evaluated', 'wholePerson', 'Evaluated run, whole-person rule'),
                            ('preDeadline', 'wholePerson', 'Last pre-deadline run, whole-person rule'),
                            ('preDeadline', 'divisible', 'Last pre-deadline run, divisible mass')):
        for q in ('all', '1', '2', '3', '4', '5'):
            c = PL[lab][rule][q]
            both = c['same'] + c['simulationEarlier'] + c['simulationLater']
            t.append([name if q == 'all' else '', 'All' if q == 'all' else q, f"{c['records']:,}", pct(c['same'] / c['records']),
                      pct(c['simulationEarlier'] / c['records']), pct(c['simulationLater'] / c['records']),
                      pct(c['simulationOnly'] / c['records']), pct(c['reconstructionOnly'] / c['records']),
                      pct(c['neither'] / c['records']), pct(c['same'] / both)])
    out['S20b'] = table(['Simulation', 'Mean-grade fifth', 'Records', 'Same department', 'More favorable',
                         'Less favorable', 'Only simulation places', 'Only official places', 'Neither places',
                         'Same, among records both place'],
                        ['---', '---', '---:', '---:', '---:', '---:', '---:', '---:', '---:', '---:'], t)
    key['placements'] = PL

    # ------------------------------------------------------------ S22a, S29, S30: tables from released-data checks
    dc = json.loads((data / 'decision-checks.json').read_text())['decision']
    t = []
    for name, label in (('all', 'All'), ('fewer_than_20_listings', 'Fewer than 20 listings'),
                        ('at_least_20_listings', 'At least 20 listings'), ('historical_level_below_30', 'Historical level below 30')):
        e = dc[name]
        for i, (m, mlab) in enumerate((('historical', 'Historical'), ('v3', 'v3'), ('combination', 'Combination'))):
            v = e[m]
            t.append([f"{label} ({v['n']:,})" if i == 0 else '', mlab, num(v['mae']), num(v['rmse']), num(v['median_absolute_error']),
                      pct(v['within_one_grade']), pct(v['official_at_least_one_grade_above']), pct(v['official_at_least_one_grade_below'])])
    out['S22a'] = table(['Stratum (count)', 'Prediction', 'MAE', 'RMSE', 'Median absolute error', 'Within one grade', '≥ 1 grade above',
                         '≥ 1 grade below'], ['---', '---', '---:', '---:', '---:', '---:', '---:', '---:'], t)
    key['S22a'] = dc

    R = json.loads((data / 'revision-checks.json').read_text())
    T = R['tails']
    out['S29a'] = table(['Measure', 'Historical', 'v3', 'Combination', 'v3 minus historical'],
                        ['---', '---:', '---:', '---:', '---'], [
        ['Excess kurtosis of the errors', f"{T['excess_kurtosis']['eH']:.1f}", f"{T['excess_kurtosis']['eV']:.1f}", f"{T['excess_kurtosis']['eM']:.1f}", ''],
        ['MAE from errors up to two grades', num(T['split_at_two_grades']['within']['baseline']), num(T['split_at_two_grades']['within']['v3']), '',
         f"{sg(T['split_at_two_grades']['within']['v3_minus_baseline'])} [{sg(T['split_at_two_grades']['within']['interval'][0])}, {sg(T['split_at_two_grades']['within']['interval'][1])}]"],
        ['MAE from the excess beyond two grades', num(T['split_at_two_grades']['beyond']['baseline']), num(T['split_at_two_grades']['beyond']['v3']), '',
         f"{sg(T['split_at_two_grades']['beyond']['v3_minus_baseline'])} [{sg(T['split_at_two_grades']['beyond']['interval'][0])}, {sg(T['split_at_two_grades']['beyond']['interval'][1])}]"],
        ['Errors of at least four grades', pct(T['at_least_four_grades']['baseline']), pct(T['at_least_four_grades']['v3']), pct(T['at_least_four_grades']['combination']), ''],
        ['MAE without its own largest 5% of errors', num(T['mae_without_own_largest_5pct']['baseline']), num(T['mae_without_own_largest_5pct']['v3']),
         num(T['mae_without_own_largest_5pct']['combination']), ''],
        [f"MAE on the {T['without_those_kinds']['n']:,} departments without the kinds of department in the tail", num(T['without_those_kinds']['mae_baseline']),
         num(T['without_those_kinds']['mae_v3']), num(T['without_those_kinds']['mae_combination']), '']])
    SL = R['slopes']
    t = [['Least squares, all', f"{SL['least_squares']:.2f}", ''],
         ["Huber's M-estimator, all", f"{SL['huber']:.2f}", f"[{SL['huber_interval'][0]:.2f}, {SL['huber_interval'][1]:.2f}]"],
         ['Least absolute deviations, all', f"{SL['least_absolute_deviations']:.2f}", f"[{SL['lad_interval'][0]:.2f}, {SL['lad_interval'][1]:.2f}]"]]
    for band, lab in (('0-2', 'absolute S below 2'), ('2-4', 'absolute S 2–4'), ('4-8', 'absolute S 4–8'), ('8-inf', 'absolute S at least 8')):
        b = SL['by_abs_S'][band]
        t.append([f"Least squares, {lab} ({b['n']:,})", f"{b['slope']:.2f}", ''])
    out['S29b'] = table(['Regression of D on S', 'Slope', 'Interval'], ['---', '---:', '---'], t)
    DE = R['decision']
    t = []
    for k in ('1', '3', '9', '19'):
        e = DE['k'][k]
        f = lambda c: f"{100 * c['share_of_evpi_captured']:.1f}% [{100 * c['interval'][0]:.1f}%, {100 * c['interval'][1]:.1f}%]".replace('-', MINUS)
        t.append([k, f"{e['tau']:.2f}", f"{e['loio_2026']['loss_baseline']:.3f} / {e['loio_2026']['loss_combination']:.3f}", f(e['loio_2026']),
                  f"{e['backtest_2025']['loss_baseline']:.3f} / {e['backtest_2025']['loss_combination']:.3f}", f(e['backtest_2025']),
                  f(e['rules_and_quota_unchanged']), f"{e['best_weight']['weight']:.2f}"])
    out['S29c'] = table(['k', 'τ', 'Pinball loss, 2026 margins: hist. / comb.', 'Share of EVPI captured', 'Pinball loss, 2025 margins: hist. / comb.',
                         'Share captured, 2025 margins', 'Share captured, rules and quota unchanged (167)', 'Best weight'],
                        ['---:', '---:', '---', '---', '---', '---', '---', '---:'], t)
    t = []
    for m, lab in (('0', 'At the prediction'), ('0.5', 'More than 0.5 grade'), ('1', 'More than 1 grade'), ('1.5', 'More than 1.5 grades'),
                   ('2', 'More than 2 grades'), ('3', 'More than 3 grades')):
        e = DE['exceeds_prediction_by_more_than'][m]
        t.append([lab, pct(e['baseline']), pct(e['combination']), pci(e)])
    out['S29d'] = table(['Official cutoff above the prediction', 'Historical', 'Combination', 'Difference (points)'],
                        ['---', '---:', '---:', '---'], t)
    MR = DE['margin_for_risk']
    key['S29d_margins'] = MR
    t = []
    for sh in ('-1.0', '-0.5', '+0.5', '+0.8', '+1.0', '+1.3'):
        a, c = R['level_shift'][sh], R['level_shift'][sh + ' centered']
        t.append([sh.replace('-', MINUS), f"{sg(a['gain'])} ({pct(a['relative'])})".replace('-', MINUS),
                  f"{sg(c['gain'])} ({pct(c['relative'])})".replace('-', MINUS)])
    out['S29e'] = table(['Shift of every simulated cutoff (grades)', 'Combination minus historical', 'With S centered on its mean'],
                        ['---:', '---', '---'], t)
    EQ = R['equity']
    def eqrow(lab, v):
        ival = f"[{sg(v['interval'][0])}, {sg(v['interval'][1])}]" if v.get('interval') else '—'
        return [lab, f"{v['n']:,} ({v['institutions']})", pct(v['private_share'], 0), f"{num(v['mae_baseline'])}/{num(v['mae_v3'])}/{num(v['mae_combination'])}",
                f"{sg(v['bias_baseline'])}/{sg(v['bias_v3'])}", f"{sg(v['gain'])} {ival}", pct(v['relative']).replace('-', MINUS),
                f"{pct(v['above_baseline'])} → {pct(v['above_combination'])}", f"{pct(v['below_baseline'])} → {pct(v['below_combination'])}",
                pct(v['combination_worse_by_half_grade']), pct(v['fewer_than_20_listings'])]
    head = ['Departments', 'Count (inst.)', 'Private', 'MAE: H/v3/C', 'Bias: H/v3', 'C minus H',
            'Relative', '≥1 above: H → C', '≥1 below: H → C', 'C worse by ≥0.5', 'Under 20 listings']
    al = ['---', '---:', '---:', '---', '---', '---', '---:', '---', '---', '---:', '---:']
    names = {'north': 'North', 'central': 'Central', 'south': 'South', 'east_and_kinmen': 'East and Kinmen'}
    t = [eqrow(names[g], EQ['regions'][g]) for g in ('north', 'central', 'south', 'east_and_kinmen')]
    t += [eqrow('Public', EQ['sector']['public']), eqrow('Private', EQ['sector']['private'])]
    out['S30a'] = table(head, al, t)
    t = []
    for g in ('north', 'central', 'south', 'east_and_kinmen'):
        for lv, ll in (('below_30', 'below 30'), ('30_and_above', '30 and above')):
            t.append(eqrow(f"{names[g]}, level {ll}", EQ['region_by_level'][f'{g}|{lv}']))
    t += [eqrow('North and central, level below 30', EQ['region_by_level']['north_and_central|below_30']),
          eqrow('South, east, and Kinmen, level below 30', EQ['region_by_level']['south_east_and_kinmen|below_30'])]
    out['S30b'] = table(head, al, t)
    t = []
    for g, lab in (('all', 'All'), ('level 0-30', 'Level 0–30'), ('level 30-40', 'Level 30–40'), ('level 40-45', 'Level 40–45'),
                   ('level 45-50', 'Level 45–50'), ('level 50-61', 'Level 50–60'), ('public', 'Public'), ('private', 'Private'),
                   ('region north', 'North'), ('region central', 'Central'), ('region south', 'South'), ('region east_and_kinmen', 'East and Kinmen'),
                   ('south, east and Kinmen below 30', 'South, east, and Kinmen, level below 30')):
        v = EQ['interval_coverage'][g]
        t.append([lab, pct(v['scaled']), pct(v['calibrated_within_level'])])
    out['S30c'] = table(['Departments', 'Scaled interval (S22d)', 'Calibrated within level bands'], ['---', '---:', '---:'], t)
    key['S30'] = {'withheld': EQ['withheld'], 'below_30_by_simulated_filling': EQ['below_30_by_simulated_filling'],
                  'underfilled': EQ['underfilled'], 'quota_share_below_30': EQ['levels']['0-30'].get('quota_share')}

    # ------------------------------------------------------------ added after the fifth simulated review
    R5 = json.loads((data / 'author-checks-round5.json').read_text())['sections']
    FR = R['fifth_review']
    DN, AU = R5['dean'], R5['aug7']
    def rule_row(lab, cov, j5, load, block, order):
        ex = load['excessOverQuota']
        return [lab, f"{cov:,}", f"{j5['covered']:,}", num(j5['mae']), sg(j5['bias']),
                f"{load['overloaded']:,}" + (f" (median {pct(ex['median'], 0)}; largest {ex['max']:.1f} times)" if load['overloaded'] else ''),
                f"{load['belowQuotaByAtLeastOne']:,}", block, order]
    t = [rule_row('Deployed whole-person rule (v2)', DN['v2']['covered1706'], DN['v2']['J5'], DN['v2']['load'],
                  f"{DN['v2']['blocking']['listings']:,} ({DN['v2']['blocking']['records']:,} records)",
                  f"{DN['v2']['order']['departmentsChangedMin']}–{DN['v2']['order']['departmentsChangedMax']}"),
         rule_row('Whole-person rule of Dean et al. (2006b, Theorem 2)', DN['dean']['covered1706'], DN['dean']['J5'], DN['dean']['load'],
                  f"{DN['dean']['blocking']['listings']:,}", f"{DN['dean']['order']['departmentsChangedMax']}"),
         rule_row('Divisible mass (Fractional)', DN['fractional']['covered1706'], DN['fractional']['J5'], DN['fractional']['load'], '—', 'None (Proposition 1)')]
    out['S11b'] = table(['Rule', 'Departments with a value', 'Covered in J5', 'MAE on covered J5', 'Bias', 'Departments over quota (excess as a share of the quota)',
                         'At least one place unused', 'Listings rejected above the lowest retained score', 'Departments changed by 20 orders'],
                        ['---', '---:', '---:', '---:', '---:', '---', '---:', '---', '---'], t)
    key['S11b'] = {'dean': DN['dean'], 'v2': DN['v2'], 'fractional': DN['fractional'], 'maxWeight': DN['maxWeight'],
                   'medianQuota': DN['medianQuota'], 'aug7': AU}

    IV = FR['intervals']
    t = []
    for d in ('-1.17', '-0.70', '-0.35', '+0.00', '+0.35', '+0.70'):
        a, b = IV['common_shift'][f'shift {d}, pad 0.0'], IV['common_shift'][f'shift {d}, pad 0.7']
        t.append([d.replace('-', MINUS), pct(a['coverage']), pct(a['official_above']), pct(a['official_below']),
                  pct(b['coverage']), pct(b['official_above']), pct(b['official_below'])])
    out['S22g'] = table(['Common shift of the 2026 errors (grades)', 'Coverage', 'Official above', 'Official below',
                         'Coverage, widened 0.7 each side', 'Official above, widened', 'Official below, widened'],
                        ['---:', '---:', '---:', '---:', '---:', '---:', '---:'], t)
    t = []
    names = {'fewer_than_20_listings': 'Fewer than 20 listings', 'level_below_30': 'Level below 30', 'private': 'Private',
             'south_east_kinmen_below_30': 'South, east, and Kinmen, level below 30', 'abs_S_at_least_4': 'Absolute S at least 4'}
    for k, v in FR['interval_subgroups'].items():
        t.append([names[k], f"{v['n']:,} ({v['institutions']})", f"{pct(v['coverage'])} [{pct(v['interval'][0])}, {pct(v['interval'][1])}]",
                  pct(v['official_above'])])
    out['S22h'] = table(['Departments', 'Count (inst.)', 'Coverage of 80% intervals', 'Official above the interval'],
                        ['---', '---:', '---', '---:'], t)
    key['S22_intervals'] = {k: IV[k] for k in ('median_width_combination', 'median_width_baseline_same_model',
                                                'coverage_baseline_same_model', 'equal_tailed')}
    key['S22_single_source'] = FR['single_source']

    RT = R5['returners']
    def rr(lab, f):
        return [lab, f(RT['before']), f(RT['afterOrUnknown'])]
    both = lambda g, k, d=1: f"{g[k]['unweighted']:.{d}f} / {g[k]['weighted']:.{d}f}"
    bothp = lambda g, k: f"{pct(g[k]['unweighted'])} / {pct(g[k]['weighted'])}"
    t = [rr('Records', lambda g: f"{g['records']:,}"), rr('Mean calibration weight', lambda g: f"{g['meanWeight']:.2f}"),
         rr('Listed departments', lambda g: both(g, 'listed')), rr('Eligible preferences', lambda g: both(g, 'eligible')),
         rr('Private share of eligible preferences', lambda g: bothp(g, 'privateShareOfEligible')),
         rr('South, east, and Kinmen share', lambda g: bothp(g, 'southEastKinmenShareOfEligible')),
         rr('Share below level 30', lambda g: bothp(g, 'levelBelow30ShareOfEligible'))]
    out['S25d'] = table(['Evaluated records', 'Last updated before the deadline', 'Last updated after it, or unknown'],
                        ['---', '---', '---'], t)

    SP = R['specifications']
    t = []
    for meas in ('MAE', 'RMSE', 'median absolute error', 'share at least one grade above'):
        rel = sorted(r['relative'] for r in SP['results'] if r['measure'] == meas)
        f = (lambda x: pct(x).replace('-', MINUS)) if meas != 'share at least one grade above' else (lambda x: spct(x))
        t.append([meas[0].upper() + meas[1:], f"{len(rel):,}", f"{sum(x < 0 for x in rel):,}", f(rel[0]), f(rel[len(rel) // 2]), f(rel[-1])])
    out['S29f'] = table(['Measure', 'Specifications', 'Combination better', 'Most favorable', 'Median', 'Least favorable'],
                        ['---', '---:', '---:', '---:', '---:', '---:'], t)
    key['S29f'] = {k: SP[k] for k in ('specifications', 'improved', 'relative_quantiles', 'mae_relative_range', 'worst_mae')}

    CT = R['contrasts']
    cn = {'subjects_changed_vs_rules_unchanged': ('Subjects changed', 'Rules unchanged'),
          'quota_unchanged_vs_changed_among_unchanged_weights': ('Rules unchanged, quota unchanged', 'Rules unchanged, quota changed'),
          'south_east_kinmen_vs_north_central_below_30': ('Level below 30: south, east, Kinmen', 'Level below 30: north, central'),
          'level_below_30_vs_30_and_above': ('Level below 30', 'Level 30 and above'),
          'fewer_than_20_vs_at_least_20_listings': ('Fewer than 20 listings', 'At least 20 listings'),
          'private_vs_public': ('Private', 'Public')}
    t = []
    for k, (a, b) in cn.items():
        c = CT[k]
        t.append([f"{a} ({c['n_a']:,}) vs {b} ({c['n_b']:,})", sg(c['gain_a']), sg(c['gain_b']),
                  f"{sg(c['difference'])} [{sg(c['interval'][0])}, {sg(c['interval'][1])}]"])
    out['S30d'] = table(['Contrast', 'Gain, first group', 'Gain, second group', 'Difference'], ['---', '---:', '---:', '---'], t)
    SU = R['support']
    t = []
    for lv, ll in (('below_30', 'Level below 30'), ('30_and_above', 'Level 30 and above')):
        for g, gl in (('lt3', 'fewer than 3'), ('ge3', 'at least 3')):
            v = SU[f'{lv}|listings_per_place_{g}']
            ival = f"[{sg(v['interval'][0])}, {sg(v['interval'][1])}]" if v.get('interval') else '—'
            t.append([f"{ll}, listings per place {gl}", f"{v['n']:,} ({v['institutions']})", f"{sg(v['gain'])} {ival}",
                      pct(v['relative']).replace('-', MINUS), sg(v['bias_v3']), f"{pct(v['above_baseline'])} → {pct(v['above_combination'])}"])
    out['S30e'] = table(['Departments', 'Count (inst.)', 'Combination minus historical', 'Relative', 'v3 bias', '≥1 above: H → C'],
                        ['---', '---:', '---', '---:', '---:', '---'], t)
    key['S30e_spearman'] = {k: v for k, v in SU.items() if k.endswith('spearman')}
    FL = FR['flags_by_level_and_sector']
    fn = {'below_30|public': 'Level below 30, public', 'below_30|private': 'Level below 30, private',
          '30_and_above|public': 'Level 30 and above, public', '30_and_above|private': 'Level 30 and above, private',
          'below_30|south_east_kinmen': 'Level below 30, south, east, and Kinmen'}
    t = []
    for k, lab in fn.items():
        v = FL[k]
        t.append([lab, f"{v['n']:,}", pct(v['up_flag_share']), pct(v['up_precision']), pct(v['up_moved_down_1']),
                  pct(v['down_flag_share']), pct(v['down_precision']), pct(v['down_moved_up_1'])])
    out['S30f'] = table(['Departments', 'Count', 'Upward flags', 'Upward precision', 'Upward flag, moved down ≥1', 'Downward flags',
                         'Downward precision', 'Downward flag, moved up ≥1'],
                        ['---', '---:', '---:', '---:', '---:', '---:', '---:', '---:'], t)
    key['fifth_review'] = {k: FR[k] for k in ('official_underfilled', 'simulated_filling_status', 'release_threshold',
                                              'institution_heterogeneity', 'fallback_rule', 'flag_moves', 'table5_family')}
    key['round5'] = {k: R5[k] for k in ('concentration', 'eligibility', 'vintage', 'convergence')}


    text = []
    for k, v in out.items():
        text.append(f'<!-- table: {k} -->\n{v}\n')
    output_path('author-tables.md').write_text('\n'.join(text))
    output_path('author-key-numbers.json').write_text(json.dumps(key, indent=1, ensure_ascii=False, default=str) + '\n')
    print('\n'.join(text))


if __name__ == '__main__':
    main()
