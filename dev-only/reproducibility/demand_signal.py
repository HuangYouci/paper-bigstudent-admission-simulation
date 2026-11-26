"""v0.15 事前規格分析：固定混合規則與冷熱方向辨識。

規格見 dev-only/review/analysis-plan-v015.md（計算前寫定；SHA-256 記於 data/manifest.json）。只讀凍結校系彙總，
不讀平台、不讀個人資料。輸出 data/demand-signal-results.json。
"""
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, REPETITIONS, SEED, load_rows, common_rows, output_path  # noqa: E402

LAMBDA = 0.4          # commit 113fcf0, 2026-08-13 01:44 +0800, final-model.mjs
DELTAS = (1.0, 2.0)   # 1.0 為主要，2.0 為敏感度
SUPPORT_CUT = 20      # v0.14 既有切點


def blend(row, lam=LAMBDA, sim='v3'):
    """事前規則：兩側皆有值時線性混合，只有一側時退回該側。"""
    s, b = row[sim], row['baseline']
    if s is not None and b is not None:
        return lam * s + (1 - lam) * b
    return s if s is not None else b


def mae(rows, key):
    return sum(abs(r[key] - r['actual']) / r['weightTotal'] for r in rows) / len(rows)


def deviations(rows):
    """D：官方相對基準的觀察偏離；S：模擬相對基準的預測偏離。"""
    out = []
    for r in rows:
        d = (r['actual'] - r['baseline']) / r['weightTotal']
        s = (r['v3'] - r['baseline']) / r['weightTotal']
        out.append((r['school'], d, s, r))
    return out


def auroc(scores_pos, scores_neg):
    """Mann–Whitney 形式，平手記 0.5。"""
    if not scores_pos or not scores_neg:
        return None
    ranked = sorted([(v, 1) for v in scores_pos] + [(v, 0) for v in scores_neg])
    rank_sum, i = 0.0, 0
    while i < len(ranked):
        j = i
        while j < len(ranked) and ranked[j][0] == ranked[i][0]:
            j += 1
        avg = (i + j + 1) / 2
        rank_sum += avg * sum(1 for k in range(i, j) if ranked[k][1] == 1)
        i = j
    n1, n0 = len(scores_pos), len(scores_neg)
    return (rank_sum - n1 * (n1 + 1) / 2) / (n1 * n0)


def spearman(x, y):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda k: v[k])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j < len(order) and v[order[j]] == v[order[i]]:
                j += 1
            for k in range(i, j):
                r[order[k]] = (i + j - 1) / 2
            i = j
        return r
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    return cov / math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))


def detection(items, delta):
    d = [x[1] for x in items]
    s = [x[2] for x in items]
    hot = [di >= delta for di in d]
    cold = [di <= -delta for di in d]
    flag_hot = [si >= delta for si in s]
    flag_cold = [si <= -delta for si in s]
    flagged = [k for k in range(len(items)) if flag_hot[k] or flag_cold[k]]
    nonzero = [k for k in flagged if d[k] != 0]
    agree = sum(1 for k in nonzero if (s[k] > 0) == (d[k] > 0))

    def pr(flags, events):
        tp = sum(1 for f, e in zip(flags, events) if f and e)
        return {
            'flags': sum(flags), 'events': sum(events), 'true_positive': tp,
            'precision': tp / sum(flags) if sum(flags) else None,
            'recall': tp / sum(events) if sum(events) else None,
        }

    slope = sum(a * b for a, b in zip(d, s)) / sum(b * b for b in s)
    return {
        'n': len(items),
        'hot': pr(flag_hot, hot),
        'cold': pr(flag_cold, cold),
        'flagged': len(flagged),
        'direction_agreement': agree / len(nonzero) if nonzero else None,
        'auroc_hot': auroc([s[k] for k in range(len(s)) if hot[k]], [s[k] for k in range(len(s)) if not hot[k]]),
        'auroc_cold': auroc([-s[k] for k in range(len(s)) if cold[k]], [-s[k] for k in range(len(s)) if not cold[k]]),
        'slope_through_origin': slope,
        'spearman': spearman(d, s),
    }


def cluster_ci(items, stat, repetitions=REPETITIONS):
    """固定預測、以學校有放回重抽，統計量於合併校系上重算。"""
    groups = {}
    for it in items:
        groups.setdefault(it[0], []).append(it)
    keys = list(groups)
    rng = random.Random(SEED)
    vals = []
    for _ in range(repetitions):
        sample = []
        for _ in keys:
            sample.extend(groups[keys[rng.randrange(len(keys))]])
        v = stat(sample)
        if v is not None:
            vals.append(v)
    vals.sort()
    return [vals[int(.025 * len(vals))], vals[int(.975 * len(vals))]]


def mix_difference(rows, lam, sim='v3'):
    items = [(r['school'], (abs(blend(r, lam, sim) - r['actual']) - abs(r['baseline'] - r['actual'])) / r['weightTotal']) for r in rows]
    point = sum(x[1] for x in items) / len(items)
    ci = cluster_ci(items, lambda smp: sum(x[1] for x in smp) / len(smp))
    return point, ci


def main():
    rows = load_rows()
    j2 = common_rows(rows, ('v3', 'baseline'))
    for r in rows:
        r['mix'] = blend(r)
    out = {'spec': 'dev-only/review/analysis-plan-v015.md', 'lambda': LAMBDA, 'seed': SEED,
           'repetitions': REPETITIONS}

    # H1 主要比較
    point, ci = mix_difference(j2, LAMBDA)
    out['h1_primary'] = {'n': len(j2), 'schools': len({r['school'] for r in j2}),
                         'mae_mix': mae(j2, 'mix'), 'mae_v3': mae(j2, 'v3'), 'mae_baseline': mae(j2, 'baseline'),
                         'difference_mix_minus_baseline': point, 'interval': ci,
                         'relative_change': point / mae(j2, 'baseline')}
    # 偏差
    out['h1_primary']['bias_mix'] = sum((r['mix'] - r['actual']) / r['weightTotal'] for r in j2) / len(j2)
    out['h1_primary']['bias_baseline'] = sum((r['baseline'] - r['actual']) / r['weightTotal'] for r in j2) / len(j2)
    out['h1_primary']['raw_mae_mix'] = sum(abs(r['mix'] - r['actual']) for r in j2) / len(j2)
    out['h1_primary']['raw_mae_baseline'] = sum(abs(r['baseline'] - r['actual']) for r in j2) / len(j2)
    out['h1_primary']['within1_mix'] = sum(abs(r['mix'] - r['actual']) / r['weightTotal'] < 1 for r in j2) / len(j2)
    out['h1_primary']['within1_baseline'] = sum(abs(r['baseline'] - r['actual']) / r['weightTotal'] < 1 for r in j2) / len(j2)

    import statistics
    ev = [(r['v3'] - r['actual']) / r['weightTotal'] for r in j2]
    eb = [(r['baseline'] - r['actual']) / r['weightTotal'] for r in j2]
    out['h1_primary']['error_correlation_v3_baseline'] = statistics.correlation(ev, eb)
    out['h1_primary']['error_sd_v3'] = statistics.stdev(ev)
    out['h1_primary']['error_sd_baseline'] = statistics.stdev(eb)

    # 完整母群涵蓋
    has = [r for r in rows if r['mix'] is not None]
    only_v3 = [r for r in has if r['baseline'] is None]
    only_b = [r for r in has if r['v3'] is None]
    out['h1_population'] = {'population': len(rows), 'covered': len(has), 'coverage': len(has) / len(rows),
                            'mae_all_covered': mae(has, 'mix'),
                            'only_v3_n': len(only_v3), 'only_baseline_n': len(only_b),
                            'neither_n': len(rows) - len(has)}

    # 同一 λ 對 v2 / Fractional
    out['h1_other_simulators'] = {}
    for sim in ('v2', 'fractional'):
        subset = common_rows(rows, (sim, 'baseline'))
        p, c = mix_difference(subset, LAMBDA, sim)
        out['h1_other_simulators'][sim] = {'n': len(subset), 'difference_mix_minus_baseline': p, 'interval': c,
                                           'mae_baseline': mae(subset, 'baseline')}

    # 描述性 λ 曲線
    curve = []
    for k in range(11):
        lam = k / 10
        curve.append({'lambda': lam,
                      'mae': sum(abs(blend(r, lam) - r['actual']) / r['weightTotal'] for r in j2) / len(j2)})
    out['h1_lambda_curve_descriptive'] = curve

    # 支援度分層下的混合
    strata = {}
    for name, cond in (('applicants_lt20', lambda r: r['applicant_count'] < SUPPORT_CUT),
                       ('applicants_ge20', lambda r: r['applicant_count'] >= SUPPORT_CUT),
                       ('confidence_normal', lambda r: r['confidence'] == 'normal'),
                       ('confidence_other', lambda r: r['confidence'] != 'normal')):
        sub = [r for r in j2 if cond(r)]
        p, c = mix_difference(sub, LAMBDA)
        strata[name] = {'n': len(sub), 'mae_mix': mae(sub, 'mix'), 'mae_v3': mae(sub, 'v3'),
                        'mae_baseline': mae(sub, 'baseline'), 'difference_mix_minus_baseline': p, 'interval': c}
    out['h1_strata'] = strata

    # H2 冷熱
    items = deviations(j2)
    out['h2'] = {}
    for delta in DELTAS:
        res = detection(items, delta)
        res['interval_direction_agreement'] = cluster_ci(items, lambda smp, dl=delta: detection(smp, dl)['direction_agreement'])
        res['interval_auroc_hot'] = cluster_ci(items, lambda smp, dl=delta: detection(smp, dl)['auroc_hot'])
        res['interval_auroc_cold'] = cluster_ci(items, lambda smp, dl=delta: detection(smp, dl)['auroc_cold'])
        res['interval_slope'] = cluster_ci(items, lambda smp, dl=delta: detection(smp, dl)['slope_through_origin'])
        res['interval_spearman'] = cluster_ci(items, lambda smp, dl=delta: detection(smp, dl)['spearman'])
        out['h2'][f'delta_{delta:g}'] = res
    h2_strata = {}
    for name, cond in (('confidence_normal', lambda r: r['confidence'] == 'normal'),
                       ('confidence_other', lambda r: r['confidence'] != 'normal'),
                       ('applicants_lt20', lambda r: r['applicant_count'] < SUPPORT_CUT),
                       ('applicants_ge20', lambda r: r['applicant_count'] >= SUPPORT_CUT)):
        sub = [it for it in items if cond(it[3])]
        h2_strata[name] = detection(sub, DELTAS[0])
    out['h2_strata_delta_1'] = h2_strata

    # 探索性對照（事前規格之外，計算後追加，稿件中標明）
    unchanged = [r for r in common_rows(rows, ('v3', 'baseline', 'prior_2025_positive_cutoff')) if r['unchangedWeights']]

    def m(rs, f):
        return sum(abs(f(r) - r['actual']) / r['weightTotal'] for r in rs) / len(rs)
    devs = [(r['v3'] - r['baseline']) / r['weightTotal'] for r in j2]
    rng = random.Random(SEED)
    placebo = []
    for _ in range(1000):
        shuffled = devs[:]
        rng.shuffle(shuffled)
        placebo.append(sum(abs(r['baseline'] + LAMBDA * d * r['weightTotal'] - r['actual']) / r['weightTotal']
                           for r, d in zip(j2, shuffled)) / len(j2))
    placebo.sort()
    out['exploratory_controls'] = {
        'note': 'post-hoc; not in pre-specified plan',
        'unchanged_rules_n': len(unchanged),
        'unchanged_mae_baseline': m(unchanged, lambda r: r['baseline']),
        'unchanged_mae_raw_prior': m(unchanged, lambda r: r['prior_2025_positive_cutoff']),
        'unchanged_mae_mix_v3': m(unchanged, lambda r: LAMBDA * r['v3'] + (1 - LAMBDA) * r['baseline']),
        'unchanged_mae_mix_raw_prior': m(unchanged, lambda r: LAMBDA * r['prior_2025_positive_cutoff'] + (1 - LAMBDA) * r['baseline']),
        'placebo_shuffled_signal_mae': {'p2.5': placebo[25], 'median': placebo[500], 'p97.5': placebo[975], 'draws': 1000},
    }

    # 只用歷史資訊的對照訊號：若任何與基準誤差不同的預測都能產生高一致率，
    # 79% 就不能只與 50% 比較。三者皆不使用 2026 結果。
    def signal_stats(signal_rows):
        comp = [(it[0], it[1], s_, it[3]) for it, s_ in signal_rows]
        res = detection(comp, DELTAS[0])
        return {'n': len(comp), 'direction_agreement': res['direction_agreement'],
                'flagged': res['flagged'], 'spearman': res['spearman'],
                'auroc_hot': res['auroc_hot'], 'auroc_cold': res['auroc_cold']}
    raw_rows = [(it, (it[3]['prior_2025_positive_cutoff'] - it[3]['baseline']) / it[3]['weightTotal'])
                for it in items if it[3]['prior_2025_positive_cutoff'] is not None]
    grand = sum(r['baseline'] / r['weightTotal'] for r in j2) / len(j2)
    grand_rows = [(it, grand - it[3]['baseline'] / it[3]['weightTotal']) for it in items]
    by_school = {}
    for r in j2:
        by_school.setdefault(r['school'], []).append(r['baseline'] / r['weightTotal'])
    school_rows = [(it, sum(by_school[it[0]]) / len(by_school[it[0]]) - it[3]['baseline'] / it[3]['weightTotal'])
                   for it in items]
    out['exploratory_history_only_signals'] = {
        'note': 'post-hoc; signals built without 2026 outcomes; delta = 1',
        'raw_2025_cutoff': signal_stats(raw_rows),
        'grand_mean_of_baseline': signal_stats(grand_rows),
        'school_mean_of_baseline': signal_stats(school_rows),
    }
    # AUROC 只以中性校系作負例（反向事件排除）
    d = [it[1] for it in items]
    sv = [it[2] for it in items]
    neutral = [k for k in range(len(d)) if abs(d[k]) < DELTAS[0]]
    out['exploratory_auroc_vs_neutral'] = {
        'note': 'post-hoc; negatives restricted to departments with |D| < 1',
        'neutral_n': len(neutral),
        'hot': auroc([sv[k] for k in range(len(d)) if d[k] >= DELTAS[0]], [sv[k] for k in neutral]),
        'cold': auroc([-sv[k] for k in range(len(d)) if d[k] <= -DELTAS[0]], [-sv[k] for k in neutral]),
    }

    target = output_path('demand-signal-results.json')
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
