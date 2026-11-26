"""Aggregate statistics for the record-level author checks (fourth and fifth revisions; plan v0.22).

Runs on the author's computer. Reads the department-level reruns that author_checks.mjs wrote to
PRIVATE_DIR, puts each rerun's v3 values in place of the evaluated ones on the released J2 set
(1,521 departments; actual cutoffs, baselines and multipliers from the released file), and computes the
paper's statistics with the released-data functions: errors of the rerun where it has a value, the fixed
combination (baseline where the rerun has no value) against the baseline with institution-cluster
intervals, the share of departments whose official cutoff is at least one grade above the prediction, and
direction agreement, and the weights on the rerun that minimize squared and absolute error. Writes
OUT_DIR/author-stats-<group>.json, which contains aggregates only.

Usage: GROUP=<runs|variants|trs|subsamples|ties|detail|levels|vintage|exante> PRIVATE_DIR=... OUT_DIR=... python3 author_stats.py
"""
import csv
import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, os.environ.get('PACKAGE_SCRIPTS', str(Path(__file__).resolve().parent)))
from analyze import PAPER, load_rows, common_rows  # noqa: E402
from decision_checks import LAMBDA, STATS, difference, flag_summary, mae_difference, summarize  # noqa: E402
from robustness_checks import departures, gain_summary, load_history, permutation_reference, rule_change  # noqa: E402

PRIVATE = Path(os.environ.get('PRIVATE_DIR', PAPER / 'private-not-released'))
OUT = Path(os.environ.get('OUT_DIR', PAPER / 'out'))
GROUP = os.environ.get('GROUP', 'runs')

RUN_IDS = ('ast_20260805T175904Z', 'ast_20260806T120005Z', 'ast_20260807T022008Z', 'ast_20260807T120012Z',
           'ast_20260808T035958Z', 'ast_20260808T095000Z', 'ast_20260813T012242Z', 'ast_20260815T150000Z')
GROUPS = {
    'runs': [f'run-{r}' for r in RUN_IDS] + [f'run-{r}-no-zero-cleaning' for r in RUN_IDS[:2]]
            + ['deadline-reconstructed', 'evaluated-pre-deadline-states', 'evaluated-updated-before-deadline', 'evaluated-main'],
    'variants': [f'variant-{v}' for v in ('main', 'registrant-scaled', 'uniform-calibrated-total', 'uniform-registrants',
                                          'exclude-no-eligible', 'collapsed-ten-grade', 'collapsed-single-grade',
                                          'bounded-0.2-5', 'bounded-0.2-10', 'truncate-5', 'truncate-10', 'truncate-20', 'truncate-40',
                                          'dedupe-grades')],
    'trs': [f'trs-{s}' for s in range(10)],
    'subsamples': [f'subsample-{p}-{s}' for p in (25, 50, 75) for s in range(5)],
    'ties': [f'ties-{s}' for s in range(20)],
    'detail': ['run-ast_20260808T035958Z', 'deadline-reconstructed', 'evaluated-main'],
    'levels': ['evaluated-main', 'run-ast_20260808T035958Z', 'deadline-reconstructed', 'variant-collapsed-ten-grade',
               'variant-collapsed-single-grade', 'variant-bounded-0.2-10', 'variant-registrant-scaled',
               'variant-uniform-calibrated-total', 'variant-truncate-20', 'variant-truncate-40', 'trs-0'],
}
LEVEL_BANDS = ((0, 30), (30, 40), (40, 45), (45, 50), (50, 61))
# Groups whose labels are many replicates get point statistics only; the others get cluster intervals.
INTERVALS = GROUP in ('runs', 'variants', 'detail')


def read_private(label, column='prediction'):
    with (PRIVATE / f'dept-{label}.csv').open(newline='') as f:
        return {int(r['gid']): (float(r[column]) if r.get(column) else None) for r in csv.DictReader(f)}


def j2_rows():
    rows = load_rows()
    history = load_history()
    with (PAPER / 'data/history-2024.csv').open(newline='') as fh:
        changed = {int(r['gid']): r['rules_changed_2024_2025'] == 'True' for r in csv.DictReader(fh)}
    for gid, h in history.items():
        h['rules_changed'] = changed.get(gid, False)
    inputs = {d['gid']: d for d in json.loads((PAPER / 'data/baseline-inputs.json').read_text())['departments']}
    for r in rows:
        r.update(history[r['gid']])
        r['rule_change'] = rule_change(inputs[r['gid']]) if r['gid'] in inputs else None
    j2 = common_rows(rows, ('v3', 'baseline'))
    assert len(j2) == 1521
    return j2


def label_stats(j2, pred, intervals, detail=False):
    rows = [dict(r) for r in j2]
    for r in rows:
        r['pred'] = pred.get(r['gid'])
    covered = [r for r in rows if r['pred'] is not None]
    p = lambda r: r['pred']
    base = lambda r: r['baseline']
    mix = lambda r: LAMBDA * r['pred'] + (1 - LAMBDA) * r['baseline'] if r['pred'] is not None else r['baseline']
    d = [(r['actual'] - r['baseline']) / r['weightTotal'] for r in covered]
    s = [(r['pred'] - r['baseline']) / r['weightTotal'] for r in covered]
    out = {'covered': len(covered), 'prediction': summarize(covered, p), 'baseline_on_covered': summarize(covered, base),
           'combination': summarize(rows, mix), 'baseline': summarize(rows, base), 'mean_S': statistics.fmean(s),
           'flags_delta1': flag_summary(d, s, 1.0), 'flags_delta2': flag_summary(d, s, 2.0)}
    out['optimal_weight'] = optimal_weight(rows)
    base_mae = out['baseline']['mae']
    out['combination_minus_baseline'] = {'difference': out['combination']['mae'] - base_mae,
                                         'relative': out['combination']['mae'] / base_mae - 1}
    if intervals:
        out['combination_minus_baseline'] = mae_difference(rows, mix, base)
        out['above_share_difference'] = difference(rows, mix, base, STATS['official_at_least_one_grade_above'])
        out['prediction_minus_baseline_on_covered'] = mae_difference(covered, p, base)
    if detail:
        for r in covered:
            r['v3'] = r['pred']
        departures(covered)
        out['permutation_reference'] = permutation_reference(covered)
        total = sum(abs(r['mix'] - r['actual']) / r['weightTotal'] - abs(r['baseline'] - r['actual']) / r['weightTotal']
                    for r in covered)
        out['rule_change'] = {name: gain_summary([r for r in covered if r['rule_change'] == name], total)
                              for name in ('unchanged', 'multipliers', 'subjects')}
        stable = [r for r in covered if r['unchangedWeights'] and r['quota_2025']]
        out['structure_unchanged_quota_identical'] = gain_summary([r for r in stable if r['official_quota'] == r['quota_2025']])
    return out


def optimal_weight(rows):
    """Weights on the rerun minimizing squared error (closed form) and MAE (grid of 0.01) where it has a value."""
    covered = [r for r in rows if r['pred'] is not None]
    num = sum((r['actual'] - r['baseline']) * (r['pred'] - r['baseline']) / r['weightTotal'] ** 2 for r in covered)
    den = sum((r['pred'] - r['baseline']) ** 2 / r['weightTotal'] ** 2 for r in covered)
    grid = [k / 100 for k in range(101)]
    mae = [statistics.fmean(abs(lam * r['pred'] + (1 - lam) * r['baseline'] - r['actual']) / r['weightTotal'] for r in covered)
           for lam in grid]
    return {'squared_error': num / den if den else None, 'absolute_error': grid[mae.index(min(mae))]}


def level_stats(j2, pred):
    """Bias and MAE by historical level (baseline divided by the multiplier total), where the rerun has a value."""
    out = {}
    for lo, hi in LEVEL_BANDS:
        rows = [r for r in j2 if lo <= r['baseline'] / r['weightTotal'] < hi and pred.get(r['gid']) is not None]
        e = [(pred[r['gid']] - r['actual']) / r['weightTotal'] for r in rows]
        out[f'{lo}-{hi}'] = {'n': len(rows), 'bias': statistics.fmean(e), 'mae': statistics.fmean(abs(x) for x in e)}
    return out


def weight_stats(j2, pred, weights=(0.106, 0.2, 0.3, 0.4, 0.5)):
    """MAE difference from the baseline for fixed combination weights other than 0.4 (baseline where no value)."""
    out = {}
    base = statistics.fmean(abs(r['baseline'] - r['actual']) / r['weightTotal'] for r in j2)
    for lam in weights:
        mix = statistics.fmean(abs((lam * pred[r['gid']] + (1 - lam) * r['baseline'] if pred.get(r['gid']) is not None
                                    else r['baseline']) - r['actual']) / r['weightTotal'] for r in j2)
        out[f'{lam:.3f}'] = {'difference': mix - base, 'relative': mix / base - 1}
    return out


def exante_rows():
    rows = load_rows()
    return [r for r in rows if r['baseline'] is not None], {r['gid'] for r in rows if r['v3'] is not None}


def main():
    if GROUP == 'exante':
        rows, released = exante_rows()
        base = lambda r: r['baseline']
        result = {'group': GROUP, 'n': len(rows), 'note': 'all released departments with a baseline; the baseline stands in where the rerun has no value or the department is withheld', 'labels': {}}
        for label in GROUPS['runs']:
            pred = read_private(label)
            p = {gid: v for gid, v in pred.items() if gid in released}
            mix = lambda r, p=p: LAMBDA * p[r['gid']] + (1 - LAMBDA) * r['baseline'] if p.get(r['gid']) is not None else r['baseline']
            result['labels'][label] = mae_difference(rows, mix, base)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f'author-stats-{GROUP}.json').write_text(json.dumps(result, indent=2) + '\n')
        for label, v in result['labels'].items():
            print(label, round(v['difference'], 3), v['interval'], round(v['relative'], 3))
        return
    j2 = j2_rows()
    if GROUP == 'vintage':
        # What was available before the deadline: the Fractional allocation (written on 7 August) without the v3
        # interpolation (13 August), and other fixed weights, on the last pre-deadline run and the deadline reconstruction.
        result = {'group': GROUP, 'note': 'pre-deadline inputs with the Fractional (marginal) cutoff and with other fixed weights', 'labels': {}}
        for label in ('run-ast_20260808T035958Z', 'deadline-reconstructed', 'evaluated-main'):
            frac = read_private(label, 'fractional')
            result['labels'][label] = {'fractional': label_stats(j2, frac, True), 'fractional_weights': weight_stats(j2, frac),
                                       'v3_weights': weight_stats(j2, read_private(label))}
            if label != 'evaluated-main':
                result['labels'][label]['v2'] = label_stats(j2, read_private(f'v2-{label}'), True)
        # Paired difference of the combination's error between the evaluated run and the pre-deadline inputs.
        ev, pre = read_private('evaluated-main'), read_private('run-ast_20260808T035958Z')
        mix = lambda pred: (lambda r: LAMBDA * pred[r['gid']] + (1 - LAMBDA) * r['baseline'] if pred.get(r['gid']) is not None else r['baseline'])
        result['evaluated_minus_pre_deadline'] = mae_difference(j2, mix(ev), mix(pre))
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f'author-stats-{GROUP}.json').write_text(json.dumps(result, indent=2) + '\n')
        for label, v in result['labels'].items():
            c = v['fractional']['combination_minus_baseline']
            print(label, round(v['fractional']['prediction']['mae'], 3), round(c['difference'], 3), c.get('interval'),
                  round(v['fractional']['flags_delta1']['direction_agreement'], 3), {k: round(x['difference'], 3) for k, x in v['v3_weights'].items()})
        return
    if GROUP == 'levels':
        result = {'group': GROUP, 'note': 'bias and MAE of reruns by historical level (baseline divided by the multiplier total), on the rerun-covered part of J2',
                  'labels': {label: level_stats(j2, read_private(label)) for label in GROUPS[GROUP]}}
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f'author-stats-{GROUP}.json').write_text(json.dumps(result, indent=2) + '\n')
        return
    result = {'group': GROUP, 'n_J2': len(j2), 'lambda': LAMBDA, 'labels': {}}
    missing = [label for label in GROUPS[GROUP] if not (PRIVATE / f'dept-{label}.csv').exists()]
    if missing:
        raise SystemExit(f'missing department files: {missing}')
    for label in GROUPS[GROUP]:
        result['labels'][label] = label_stats(j2, read_private(label), INTERVALS, detail=GROUP == 'detail')
        if GROUP == 'variants' and label == 'variant-main':
            # The Fractional (marginal) cutoff of the same run, for the integerization comparison.
            result['labels']['fractional-main'] = label_stats(j2, read_private(label, 'fractional'), INTERVALS)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'author-stats-{GROUP}.json').write_text(json.dumps(result, indent=2) + '\n')
    for label, v in result['labels'].items():
        c = v['combination_minus_baseline']
        print(label, v['covered'], round(v['prediction']['mae'], 3), round(c['difference'], 3), c.get('interval'),
              round(c['relative'], 3), round(v['flags_delta1']['direction_agreement'], 3))


if __name__ == '__main__':
    main()
