"""Aggregate statistics added after the fifth round of simulated reviews (exploratory; plan v0.24).

Runs only on the author's computer: it reads the department-level reruns and resampling draws that author_checks.mjs
wrote to PRIVATE_DIR and prints aggregates only.

  vintage      the noon rerun's gain over the evaluated rerun's gain (and the deadline reconstruction's), with a paired
               institution-cluster interval (4,000 resamples, seed 20260922) on the released J2 set;
  convergence  how many calibrations did not converge in the delete-half replicates and the learning-curve draws, and
               the mean gain of those replicates against the converged ones.

Usage: PRIVATE_DIR=... PAPER_DIR=... python3 author_round5_stats.py > out.json
"""
import collections
import csv
import json
import os
import random
import statistics

PAPER = os.environ['PAPER_DIR']
PRIVATE = os.environ['PRIVATE_DIR']
LAMBDA = 0.4
SEED = 20260922
REPS = 4000


def number(x):
    return float(x) if x not in ('', None) else None


def vintage():
    rows = list(csv.DictReader(open(os.path.join(PAPER, 'data/department-benchmark.csv'), encoding='utf-8')))
    j2 = [r for r in rows if number(r['v3']) is not None and number(r['baseline']) is not None]
    assert len(j2) == 1521

    def load(name):
        return {int(r['gid']): number(r['prediction']) for r in csv.DictReader(open(os.path.join(PRIVATE, name)))}
    runs = {'noon': load('dept-run-ast_20260808T035958Z.csv'), 'evaluated': load('dept-run-ast_20260815T150000Z.csv'),
            'deadline': load('dept-deadline-reconstructed.csv')}

    def paired(r, pred):
        a, b, w = number(r['actual']), number(r['baseline']), number(r['weightTotal'])
        m = LAMBDA * pred + (1 - LAMBDA) * b if pred is not None else b
        return (abs(m - a) - abs(b - a)) / w
    cells = {}
    for r in j2:
        g = int(r['gid'])
        cells.setdefault(r['school'], []).append({k: paired(r, v.get(g)) for k, v in runs.items()})
    keys = list(cells)

    def stat(sample):
        return {k: sum(d[k] for d in sample) / len(sample) for k in runs}
    point = stat([d for k in keys for d in cells[k]])
    rng = random.Random(SEED)
    draws = collections.defaultdict(list)
    for _ in range(REPS):
        sample = []
        for _ in keys:
            sample.extend(cells[keys[rng.randrange(len(keys))]])
        s = stat(sample)
        for k in ('noon', 'deadline'):
            draws[k + '_minus_evaluated'].append(s[k] - s['evaluated'])
            draws[k + '_over_evaluated'].append(s[k] / s['evaluated'])

    def q(v):
        v = sorted(v)
        return [v[int(.025 * len(v))], v[int(.975 * len(v))]]
    out = {'n': len(j2), 'institutions': len(keys), 'gain': point, 'repetitions': REPS, 'seed': SEED}
    for k in ('noon', 'deadline'):
        out[k + '_minus_evaluated'] = {'difference': point[k] - point['evaluated'], 'interval': q(draws[k + '_minus_evaluated'])}
        out[k + '_over_evaluated'] = {'ratio': point[k] / point['evaluated'], 'interval': q(draws[k + '_over_evaluated'])}
    return out


def convergence():
    out = {}
    for name, f in (('halfsamples_evaluated', 'halfsample-reps.jsonl'),
                    ('halfsamples_noon', 'halfsample-reps-ast_20260808T035958Z.jsonl')):
        reps = [json.loads(line) for line in open(os.path.join(PRIVATE, f))]
        bad = [r for r in reps if not r.get('converged')]
        out[name] = {'replicates': len(reps), 'not_converged': len(bad),
                     'mean_gain_not_converged': statistics.fmean(r['mixMinusBaseline'] for r in bad) if bad else None,
                     'mean_gain_converged': statistics.fmean(r['mixMinusBaseline'] for r in reps if r.get('converged'))}
    reps = [json.loads(line) for line in open(os.path.join(PRIVATE, 'curve-reps.jsonl'))]
    by_k = collections.defaultdict(list)
    for r in reps:
        by_k[r['k']].append(r)
    curve = {}
    for k, v in sorted(by_k.items()):
        good = [r['mixMinusBaseline'] for r in v if r['converged']]
        bad = [r['mixMinusBaseline'] for r in v if not r['converged']]
        curve[f'{k}/8'] = {'records': v[0]['records'], 'draws': len(v), 'not_converged': len(bad),
                           'mean_gain_converged': statistics.fmean(good) if good else None,
                           'mean_gain_not_converged': statistics.fmean(bad) if bad else None}
    out['learning_curve'] = curve
    return out


if __name__ == '__main__':
    print(json.dumps({'note': 'exploratory (plan v0.24); aggregates only', 'vintage': vintage(),
                      'convergence': convergence()}, indent=2))
