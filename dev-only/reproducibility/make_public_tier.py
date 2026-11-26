"""Write the public tier of the department files from the controlled tier (author-side tool, v0.26).

The controlled tier is the set of department files from which every statistic in the manuscript and supplement is
computed: department-benchmark.csv, weighting-granularity-departments.csv and engine-2026.csv as produced by
suppress_small_cells.py and the engine reconstruction. It goes to the editor and the reviewers and is not posted.
The public tier
  1. withholds every v1, v2 and Fractional value and the five alternative calibrations, which equal one record's
     weighted score or follow it closely;
  2. releases v3 (and its archived copy and simulated filling status) only where the platform's own display rule
     holds (confidence "normal", which requires at least 18 listings) and the interpolation moved the value away from
     the marginal record's score, so that no released v3 equals one record's weighted score;
  3. withholds the two engine columns that mix in v3 wherever v3 is withheld;
  4. adds institution-level sums from which Table 2 can be recomputed: overall sums for every column of Table 2, and,
     for its intervals, per-cluster sums of paired differences between simulation versions only, with institutions
     that have fewer than five common departments merged into one cluster.
Statistics on sets that include withheld values (for example the 1,521 departments of J2) are published as
aggregates; differencing nested aggregates against the public file could narrow some withheld v3 values, which the
manuscript states (Supplement S3).

Usage: python3 make_public_tier.py --out DIR      (DIR receives data/ files of the public tier and public-tier.json)
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

PAPER = Path(__file__).resolve().parents[2]
WITHHELD_ALWAYS = ('v1', 'v2', 'fractional')
WITH_V3 = ('v3', 'archived_v3', 'quota_status')
ENGINE_WITH_V3 = ('august_rule', 'august_rule_engine')
METHODS = ('v1', 'v2', 'fractional', 'v3', 'baseline')
MIN_CLUSTER = 5


def read(path):
    with path.open(encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def text(fields, rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def num(x):
    return float(x) if x not in ('', None) else None


def public_v3(row):
    v3, frac = num(row['v3']), num(row['fractional'])
    return row['confidence'] == 'normal' and v3 is not None and frac is not None and abs(v3 - frac) > 1e-9


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    out = Path(parser.parse_args().out)
    (out / 'data').mkdir(parents=True, exist_ok=True)

    fields, rows = read(PAPER / 'data/department-benchmark.csv')
    keep = {r['gid']: public_v3(r) for r in rows}
    public_rows = []
    for r in rows:
        p = dict(r)
        for k in WITHHELD_ALWAYS:
            p[k] = ''
        if not keep[r['gid']]:
            for k in WITH_V3:
                p[k] = ''
        public_rows.append(p)
    bench = text(fields, public_rows)
    (out / 'data/department-benchmark.csv').write_text(bench, encoding='utf-8')

    efields, erows = read(PAPER / 'data/engine-2026.csv')
    for e in erows:
        if not keep.get(e['gid'], False):
            for k in ENGINE_WITH_V3:
                e[k] = ''
    engine = text(efields, erows)
    (out / 'data/engine-2026.csv').write_text(engine, encoding='utf-8')

    # Institution sums for Table 2 on J5.
    j5 = [r for r in rows if all(num(r[m]) is not None for m in METHODS) and num(r['actual'])]
    err = lambda r, m: (num(r[m]) - num(r['actual'])) / num(r['weightTotal'])
    size = {}
    for r in j5:
        size[r['school']] = size.get(r['school'], 0) + 1
    cluster_of = {s: (s if n >= MIN_CLUSTER else 'merged small institutions') for s, n in size.items()}
    names = sorted(set(cluster_of.values()))
    label = {name: f'C{k + 1:02d}' for k, name in enumerate(names)}
    pairs = (('v2', 'v1'), ('fractional', 'v2'), ('v3', 'fractional'), ('v3', 'v2'))
    clusters = {}
    for r in j5:
        c = label[cluster_of[r['school']]]
        d = clusters.setdefault(c, {'cluster': c, 'departments': 0, **{f'sum_abs_{a}_minus_abs_{b}': 0.0 for a, b in pairs}})
        d['departments'] += 1
        for a, b in pairs:
            d[f'sum_abs_{a}_minus_abs_{b}'] += abs(err(r, a)) - abs(err(r, b))
    cfields = ['cluster', 'departments'] + [f'sum_abs_{a}_minus_abs_{b}' for a, b in pairs]
    crow = [{k: (f'{v:.10f}' if isinstance(v, float) else v) for k, v in clusters[c].items()} for c in sorted(clusters)]
    sums = text(cfields, crow)
    (out / 'data/institution-sums.csv').write_text(sums, encoding='utf-8')
    overall = {'departments_J5': len(j5), 'institutions_J5': len(size), 'clusters': len(clusters),
               'merged_institutions': sum(1 for s in size if cluster_of[s] != s),
               'sum_quota': sum(int(r['official_quota']) for r in j5), 'methods': {}}
    for m in METHODS:
        overall['methods'][m] = {
            'sum_abs_error': sum(abs(err(r, m)) for r in j5), 'sum_error': sum(err(r, m) for r in j5),
            'sum_quota_times_abs_error': sum(int(r['official_quota']) * abs(err(r, m)) for r in j5),
            'sum_abs_raw_error': sum(abs(num(r[m]) - num(r['actual'])) for r in j5),
            'released_controlled_tier': sum(num(r[m]) is not None for r in rows)}

    j2 = [r for r in rows if num(r['v3']) is not None and num(r['baseline']) is not None]
    summary = {
        'rule': ('public tier: v1, v2, Fractional and the alternative calibrations withheld; v3, its archived copy and the '
                 'simulated filling status released only where confidence is normal and v3 differs from Fractional; engine '
                 'columns that mix in v3 withheld where v3 is withheld'),
        'released_v3': sum(keep.values()), 'released_v3_in_J2': sum(keep[r['gid']] for r in j2), 'J2': len(j2),
        'withheld_v3_in_J2': sum(not keep[r['gid']] for r in j2),
        'withheld_in_J2_by_reason': {'confidence insufficient': sum(r['confidence'] != 'normal' for r in j2),
                                     'normal but equal to Fractional': sum(r['confidence'] == 'normal' and not keep[r['gid']] for r in j2)},
        'table2_sums': overall,
        'sha256': {'department-benchmark.csv': hashlib.sha256(bench.encode()).hexdigest(),
                   'engine-2026.csv': hashlib.sha256(engine.encode()).hexdigest(),
                   'institution-sums.csv': hashlib.sha256(sums.encode()).hexdigest()},
        'controlled_tier_sha256': {name: hashlib.sha256((PAPER / 'data' / name).read_bytes()).hexdigest()
                                   for name in ('department-benchmark.csv', 'engine-2026.csv', 'weighting-granularity-departments.csv')}}
    (out / 'data/public-tier.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('released_v3', 'released_v3_in_J2', 'withheld_v3_in_J2', 'withheld_in_J2_by_reason')}, indent=1))


if __name__ == '__main__':
    main()
