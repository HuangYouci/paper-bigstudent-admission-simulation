"""What a reader can recompute from the public tier alone (v0.26).

  table2       Table 2 from the sums in public-tier.json, and the interval for v3 minus v2 from the cluster sums in
               institution-sums.csv (institutions with fewer than five common departments are merged into one cluster,
               so this interval differs slightly from the one reported, which resamples the 58 institutions);
  public_set   the main comparison, direction agreement and the engine comparisons on the departments whose v3 the
               public tier releases.
Uses the public files only (department-benchmark.csv, engine-2026.csv, institution-sums.csv, public-tier.json) and
runs only on the public tier; with the controlled files, write the public tier to a separate folder with
make_public_tier.py and run it there. Writes public-checks.json.
"""
import csv
import json
import random
import sys
from pathlib import Path

PAPER = Path(__file__).resolve().parents[2]
REPS, SEED, LAMBDA = 4000, 20260922, 0.4


def num(x):
    return float(x) if x not in ('', None) else None


def interval(cells, reps=REPS, seed=SEED):
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        pick = [cells[rng.randrange(len(cells))] for _ in cells]
        vals.append(sum(a for a, _ in pick) / sum(b for _, b in pick))
    vals.sort()
    return [vals[int(.025 * reps)], vals[int(.975 * reps)]]


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from analyze import output_path, tier
    if tier() != 'public':
        raise SystemExit('public_checks.py runs on the public tier; see make_public_tier.py')
    data = PAPER / 'data'
    tier = json.loads((data / 'public-tier.json').read_text())
    sums = tier['table2_sums']
    n = sums['departments_J5']
    table2 = {m: {'mae': s['sum_abs_error'] / n, 'quota_weighted_mae': s['sum_quota_times_abs_error'] / sums['sum_quota'],
                  'bias': s['sum_error'] / n, 'raw_mae': s['sum_abs_raw_error'] / n}
              for m, s in sums['methods'].items()}
    with (data / 'institution-sums.csv').open(newline='') as f:
        clusters = list(csv.DictReader(f))
    cells = [(float(c['sum_abs_v3_minus_abs_v2']), int(c['departments'])) for c in clusters]
    v3_minus_v2 = {'difference': sum(a for a, _ in cells) / sum(b for _, b in cells), 'interval': interval(cells),
                   'clusters': len(cells)}

    with (data / 'department-benchmark.csv').open(newline='') as f:
        rows = list(csv.DictReader(f))
    with (data / 'engine-2026.csv').open(newline='') as f:
        engine = {r['gid']: r for r in csv.DictReader(f)}
    sample = []
    for r in rows:
        v3, base, actual, w = num(r['v3']), num(r['baseline']), num(r['actual']), num(r['weightTotal'])
        if v3 is None or base is None:
            continue
        e = engine[r['gid']]
        eH, eV = (base - actual) / w, (v3 - actual) / w
        sample.append({'school': r['school'], 'eH': eH, 'eV': eV, 'eM': LAMBDA * eV + (1 - LAMBDA) * eH,
                       'eE': (num(e['engine_final']) - actual) / w,
                       'eA': (num(e['august_rule_engine']) - actual) / w if num(e['august_rule_engine']) is not None else None,
                       'S': eV - eH, 'D': -eH})
    def comparison(a, b):
        s = [r for r in sample if r[a] is not None and r[b] is not None]
        groups = {}
        for r in s:
            g = groups.setdefault(r['school'], [0.0, 0])
            g[0] += abs(r[a]) - abs(r[b])
            g[1] += 1
        cells_ = list(groups.values())
        d = sum(x for x, _ in cells_) / len(s)
        return {'n': len(s), 'institutions': len(cells_), 'difference': d, 'relative': d / (sum(abs(r[b]) for r in s) / len(s)),
                'interval': interval([tuple(c) for c in cells_])}
    flagged = [r for r in sample if abs(r['S']) >= 1 and r['D'] != 0]
    out = {'note': 'recomputable from the public tier', 'table2': table2, 'table2_v3_minus_v2': v3_minus_v2,
           'public_set': {'departments': len(sample), 'combination_vs_baseline': comparison('eM', 'eH'),
                          'combination_vs_engine': comparison('eM', 'eE'), 'august_rule_vs_engine': comparison('eA', 'eE'),
                          'engine_vs_baseline': comparison('eE', 'eH'),
                          'direction_agreement': {'flagged': len(flagged),
                                                  'agreement': sum((r['S'] > 0) == (r['D'] > 0) for r in flagged) / len(flagged)}}}
    path = output_path('public-checks.json')
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(path)


if __name__ == '__main__':
    main()
