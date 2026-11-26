"""Run-level summaries of the eight saved 2026 runs (author-side; the department values are not released).

The platform did not save how many users had listed each department at each run, so a run's
department values cannot be screened for small cells; they are therefore not released. This script
reads the author's file of saved run values (ARCHIVED_RUNS_CSV), keeps only departments whose
final-run values are released (at least five listings), and writes run-level summaries:
  1. each run's coverage and error, and the error on the departments common to the seven runs
     with valid timestamps (Supplement S6);
  2. the last output saved before the registration deadline (a v2 run at 12:00 on 8 August,
     Taipei time): its combination with the historical baseline, and its hot and cold flags,
     raw and after level corrections available before the results (Section 6.10, Supplement S6).
Run metadata (times, sample sizes, versions) come from the platform's run documents, as saved by
archived_runs.mjs. Writes data/archived-run-results.json when WRITE_REFERENCE=1.
"""
import csv
import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, load_rows, output_path  # noqa: E402
from history_checks import diff_with_interval, err, load_history, mae  # noqa: E402

LAMBDA = 0.4
DELTA = 1.0
LAST_RUN_BEFORE_DEADLINE = 'ast_20260808T035958Z'   # 12:00 on 8 August 2026, Taipei time
K = 5


def flags(rows, d_key, s_key, delta=DELTA):
    out = {}
    for side, sign in (('hot', 1), ('cold', -1)):
        flagged = [r for r in rows if sign * r[s_key] >= delta]
        events = [r for r in rows if sign * r[d_key] >= delta]
        tp = [r for r in flagged if sign * r[d_key] >= delta]
        opposite = [r for r in flagged if -sign * r[d_key] >= delta]
        out[side] = {'flags': len(flagged), 'events': len(events),
                     'precision': len(tp) / len(flagged) if flagged else None,
                     'recall': len(tp) / len(events) if events else None,
                     'moved_one_grade_the_other_way': len(opposite)}
    return out


def main():
    meta = json.loads((PAPER / 'data/archived-run-results.json').read_text())
    keep = ('runId', 'startedAt', 'completedAt', 'sampleCount', 'algorithmVersion', 'status',
            'departmentDocuments', 'cutoffField', 'timeOrderValid')
    runs = [{k: r[k] for k in keep} for r in meta['rows']]
    rows = {r['gid']: r for r in load_rows() if r['applicant_count'] >= K}
    with Path(os.environ['ARCHIVED_RUNS_CSV']).open(newline='') as handle:
        saved = {int(r['gid']): r for r in csv.DictReader(handle)}
    for run in runs:
        rid = run['runId']
        values = {g: float(saved[g][rid]) for g in rows if g in saved and saved[g].get(rid, '') != ''}
        own = [dict(rows[g], run=v) for g, v in values.items()]
        paired = [r for r in own if r['baseline'] is not None]
        run.update({'supported': len(own), 'ownMAE': mae(own, 'run'), 'paired': len(paired),
                    'pairedMAE': mae(paired, 'run'), 'pairedBaselineMAE': mae(paired, 'baseline')})
    series = [r['runId'] for r in runs if r['timeOrderValid']]
    common = [g for g, r in rows.items() if r['baseline'] is not None and g in saved
              and all(saved[g].get(rid, '') != '' for rid in series)]
    common_metrics = {'n': len(common), 'baselineMAE': mae([rows[g] for g in common], 'baseline'), 'runs': [
        {'runId': rid, 'mae': mae([dict(rows[g], run=float(saved[g][rid])) for g in common], 'run')} for rid in series]}

    # The last output saved before the deadline, combined with history and read as hot/cold flags.
    history = load_history()
    back = [(h['b25'] - h['cutoff_2025']) / h['weight_total_2025'] for h in history.values()
            if h['b25'] is not None and h['cutoff_2025'] and h['weight_total_2025']]
    bias25 = statistics.fmean(back)
    pre = []
    for g, r in rows.items():
        value = saved.get(g, {}).get(LAST_RUN_BEFORE_DEADLINE, '')
        if value != '' and r['baseline'] is not None:
            v = float(value)
            d = err(r, 'baseline') * -1
            s = (v - r['baseline']) / r['weightTotal']
            pre.append(dict(r, pre=v, pre_mix=LAMBDA * v + (1 - LAMBDA) * r['baseline'], D=d, S=s))
    mean_s = statistics.fmean(r['S'] for r in pre)
    for r in pre:
        r['S_own_centred'] = r['S'] - mean_s
        r['D_backtest'] = r['D'] + bias25
        r['S_backtest'] = r['S'] + bias25
    last = {'run': LAST_RUN_BEFORE_DEADLINE, 'algorithm': 'v2', 'n': len(pre), 'mae_v2': mae(pre, 'pre'),
            'mae_mix': mae(pre, 'pre_mix'), 'mae_baseline': mae(pre, 'baseline'),
            'mix_minus_baseline': diff_with_interval(pre, 'pre_mix', 'baseline'),
            'mean_S': mean_s, 'baseline_backtest_bias_2025': bias25,
            'flags_raw': flags(pre, 'D', 'S'),
            'flags_S_centred_on_own_mean': flags(pre, 'D', 'S_own_centred'),
            'flags_backtest_bias_removed': flags(pre, 'D_backtest', 'S_backtest')}
    out = {'note': 'Run-level summaries computed by archived_run_summary.py from the saved run values of departments '
                   'with at least five listings; the department values themselves are not released.',
           'rows': runs, 'commonMetrics': common_metrics, 'lastOutputBeforeDeadline': last}
    output_path('archived-run-results.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
