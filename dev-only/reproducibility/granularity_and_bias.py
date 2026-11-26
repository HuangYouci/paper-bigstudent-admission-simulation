"""v0.16：H5 放大偏差結構（凍結彙總即可重現），H4 加權粒度指標（需先有 weighting-granularity-departments.csv）。

規格：dev-only/review/analysis-plan-v016.md。只讀校系層級資料，不讀個人資料。
輸出：data/cutoff-level-bias.json；若粒度 CSV 存在，另輸出 data/weighting-granularity-results.json。
"""
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, REPETITIONS, SEED, load_rows, common_rows, input_path, output_path  # noqa: E402
from demand_signal import auroc  # noqa: E402

LAMBDA = 0.4
LEVELS = ((0, 30), (30, 40), (40, 45), (45, 50), (50, 61))
CONFIGS = ('uniform', 'ew2', 'ew3', 'ew6', 'ew61', 'eq3')


def std_err(row, value):
    return (value - row['actual']) / row['weightTotal']


def summary(rows, key):
    errs = [std_err(r, key(r)) for r in rows]
    return {'bias': sum(errs) / len(errs), 'mae': sum(map(abs, errs)) / len(errs)}


def level_bias(rows):
    out = {}
    for grouping, level_of in (('by_baseline_level_pre_result', lambda r: r['baseline'] / r['weightTotal']),
                               ('by_actual_level_post_hoc', lambda r: r['actual'] / r['weightTotal'])):
        groups = []
        for lo, hi in LEVELS:
            sub = [r for r in rows if lo <= level_of(r) < hi]
            groups.append({'level': f'{lo}-{min(hi, 60)}', 'n': len(sub),
                           'v3': summary(sub, lambda r: r['v3']),
                           'baseline': summary(sub, lambda r: r['baseline']),
                           'mix': summary(sub, lambda r: LAMBDA * r['v3'] + (1 - LAMBDA) * r['baseline'])})
        out[grouping] = groups
    return out


def cluster_diff(rows, a, b):
    groups = {}
    for r in rows:
        groups.setdefault(r['school'], []).append(abs(std_err(r, a(r))) - abs(std_err(r, b(r))))
    cells = [(sum(v), len(v)) for v in groups.values()]
    rng = random.Random(SEED)
    samples = []
    for _ in range(REPETITIONS):
        pick = [cells[rng.randrange(len(cells))] for _ in cells]
        samples.append(sum(t for t, _ in pick) / sum(c for _, c in pick))
    samples.sort()
    return {'difference': sum(t for t, _ in cells) / sum(c for _, c in cells),
            'interval': [samples[int(.025 * REPETITIONS)], samples[int(.975 * REPETITIONS)]]}


def granularity(rows):
    path = input_path('weighting-granularity-departments.csv')
    if not path.is_file():
        return None
    with path.open(encoding='utf-8', newline='') as handle:
        table = {int(r['gid']): {k: (float(v) if v != '' else None) for k, v in r.items() if k != 'gid'}
                 for r in csv.DictReader(handle)}
    for r in rows:
        r.update({f'g_{k}': v for k, v in table[r['gid']].items()})
    # ew3 必須等於凍結 v3
    worst = max(abs(r['g_ew3'] - r['v3']) for r in rows if r['v3'] is not None)
    assert worst < 1e-6, 'ew3 與凍結 v3 不符'
    j2 = common_rows(rows, ('v3', 'baseline'))
    fixed = [r for r in j2 if all(r[f'g_{c}'] is not None for c in CONFIGS)]
    res = {'fixed_set_n': len(fixed), 'fixed_set_schools': len({r['school'] for r in fixed}), 'configs': {}}
    for c in CONFIGS:
        key = f'g_{c}'
        own = [r for r in rows if r[key] is not None]
        s = summary(fixed, lambda r, k=key: r[k])
        mix = summary(fixed, lambda r, k=key: LAMBDA * r[k] + (1 - LAMBDA) * r['baseline'])
        d = [(r['actual'] - r['baseline']) / r['weightTotal'] for r in fixed]
        sv = [(r[key] - r['baseline']) / r['weightTotal'] for r in fixed]
        flagged = [k for k in range(len(fixed)) if abs(sv[k]) >= 1 and d[k] != 0]
        agree = sum((sv[k] > 0) == (d[k] > 0) for k in flagged) / len(flagged) if flagged else None
        entry = {'coverage': len(own) / len(rows), 'estimates': len(own), 'mae': s['mae'], 'bias': s['bias'],
                 'mix_mae': mix['mae'], 'direction_agreement_delta1': agree, 'flagged_delta1': len(flagged),
                 'auroc_hot_delta1': auroc([sv[k] for k in range(len(d)) if d[k] >= 1], [sv[k] for k in range(len(d)) if d[k] < 1])}
        if c != 'ew3':
            entry['difference_vs_ew3'] = cluster_diff(fixed, lambda r, k=key: r[k], lambda r: r['g_ew3'])
        res['configs'][c] = entry
    res['baseline_mae_fixed'] = summary(fixed, lambda r: r['baseline'])['mae']
    return res


def main():
    rows = load_rows()
    j2 = common_rows(rows, ('v3', 'baseline'))
    bias = {'spec': 'dev-only/review/analysis-plan-v016.md (H5, exploratory)', 'n': len(j2), **level_bias(j2)}
    # 正文 6.7 舉例的選取範圍：採計未變、至少 60 人選填、|S|≥1
    pool = [r for r in j2 if r['unchangedWeights'] and r['applicant_count'] >= 60
            and abs((r['v3'] - r['baseline']) / r['weightTotal']) >= 1]
    opposite = [r for r in pool if ((r['v3'] - r['baseline']) * (r['actual'] - r['baseline']) < 0)
                and abs((r['actual'] - r['baseline']) / r['weightTotal']) >= 1]
    bias['illustration_pool'] = {'flagged_unchanged_ge60': len(pool), 'opposite_by_at_least_one_grade': len(opposite)}
    output_path('cutoff-level-bias.json').write_text(json.dumps(bias, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(bias, ensure_ascii=False, indent=1))
    g = granularity(rows)
    if g is not None:
        g['spec'] = 'dev-only/review/analysis-plan-v016.md (H4)'
        output_path('weighting-granularity-results.json').write_text(json.dumps(g, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(g, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
