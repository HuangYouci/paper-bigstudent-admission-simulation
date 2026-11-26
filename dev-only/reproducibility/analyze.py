"""以固定校系彙總資料重現論文表格，不讀取或修改平台。"""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics

PAPER = Path(__file__).resolve().parents[2]
METHODS = ('v1', 'v2', 'fractional', 'v3', 'baseline')
REPETITIONS = 4000
SEED = 20260922


def input_path(name):
    """Released file in data/, or another copy named by an environment variable.

    Every published statistic is computed from the released files (data/suppression.json).
    ARCHIVED_RUNS_CSV names the author's file of earlier saved runs, which is not released;
    BENCHMARK_CSV and GRANULARITY_CSV exist for the author's checks against the full files.
    """
    variable = {'department-benchmark.csv': 'BENCHMARK_CSV', 'weighting-granularity-departments.csv': 'GRANULARITY_CSV',
                'archived-run-cutoffs.csv': 'ARCHIVED_RUNS_CSV'}.get(name)
    return Path(os.environ[variable]) if variable and os.environ.get(variable) else PAPER / 'data' / name


def output_path(name):
    """Outputs go to out/; WRITE_REFERENCE=1 regenerates the stored reference files in data/."""
    folder = PAPER / ('data' if os.environ.get('WRITE_REFERENCE') == '1' else 'out')
    folder.mkdir(exist_ok=True)
    return folder / name


def tier():
    """'controlled' when data/department-benchmark.csv is the controlled-tier file named in manifest.json, 'public' when
    it is the public-tier file named in public-tier.json, otherwise 'unknown'."""
    source = PAPER / 'data' / 'department-benchmark.csv'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest == json.loads((PAPER / 'data/manifest.json').read_text())['departmentCsvSHA256']:
        return 'controlled'
    public = PAPER / 'data' / 'public-tier.json'
    if public.exists() and digest == json.loads(public.read_text())['sha256']['department-benchmark.csv']:
        return 'public'
    return 'unknown'


def load_rows():
    """驗證資料雜湊、型別與研究分母。"""
    source = input_path('department-benchmark.csv')
    manifest = json.loads((PAPER / 'data/manifest.json').read_text())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != manifest['departmentCsvSHA256'] and not os.environ.get('BENCHMARK_CSV'):
        if tier() == 'public':
            raise SystemExit('This script needs the controlled-tier department files, which go to the editor and the '
                             'reviewers; the public tier supports public_checks.py (README, "Disclosure control").')
        raise ValueError('校系資料雜湊與封存紀錄不符')
    numeric = ('actual', 'weightTotal', *METHODS, 'archived_v3', 'prior_2025_positive_cutoff')
    counts = ('gid', 'official_quota', 'applicant_count', 'prior_record_count', 'prior_positive_cutoff_count')
    with source.open(encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in numeric:
            row[key] = float(row[key]) if row[key] != '' else None
        for key in counts:
            row[key] = int(row[key])
        for key in ('unchangedWeights', 'no_history_in_snapshot'):
            if row[key] not in ('True', 'False'):
                raise ValueError('布林欄位格式錯誤')
            row[key] = row[key] == 'True'
    validate_rows(rows)
    return rows


def validate_rows(rows):
    """拒絕重複校系、非有限數值及非法倍率。"""
    if len({row['gid'] for row in rows}) != len(rows):
        raise ValueError('重複校系識別碼')
    for row in rows:
        for key in ('actual', 'weightTotal'):
            if not isinstance(row[key], (int, float)) or not math.isfinite(row[key]):
                raise ValueError('真值或倍率不是有限數值')
        if row['weightTotal'] <= 0:
            raise ValueError('倍率總和必須大於零')
        for key in (*METHODS, 'archived_v3'):
            value = row.get(key)
            if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise ValueError('預測值必須為有限數值或缺值')


def common_rows(rows, methods):
    """缺值校系排除於誤差計算，仍保留於涵蓋率分母。"""
    validate_rows(rows)
    return [row for row in rows if all(row.get(method) is not None for method in methods)]


def metrics(rows, method, weight_key=None):
    """回傳標準化 MAE、偏差與原始加權總分 MAE。"""
    if not rows:
        raise ValueError('共同集合為空')
    weights = [float(row[weight_key]) if weight_key else 1.0 for row in rows]
    if any(not math.isfinite(w) or w < 0 for w in weights) or sum(weights) <= 0:
        raise ValueError('評估權重必須非負且總和大於零')
    diffs = [row[method] - row['actual'] for row in rows]
    standardized = [diff / row['weightTotal'] for diff, row in zip(diffs, rows)]
    denominator = sum(weights)
    return {
        'n': len(rows),
        'mae': sum(w * abs(e) for w, e in zip(weights, standardized)) / denominator,
        'bias': sum(w * e for w, e in zip(weights, standardized)) / denominator,
        'raw_mae': sum(w * abs(e) for w, e in zip(weights, diffs)) / denominator,
    }


def clustered_difference(rows, first, second, repetitions=REPETITIONS):
    """固定預測，以學校為群聚抽樣單位、以校系為誤差平均單位。"""
    if repetitions < 40 or not rows:
        raise ValueError('重抽次數或共同集合不足')
    groups = {}
    for row in rows:
        difference = (abs(row[first] - row['actual']) - abs(row[second] - row['actual'])) / row['weightTotal']
        groups.setdefault(row['school'], []).append(difference)
    cells = [(sum(values), len(values)) for values in groups.values()]
    rng = random.Random(SEED)
    samples = []
    for _ in range(repetitions):
        selected = [cells[rng.randrange(len(cells))] for _ in cells]
        samples.append(sum(total for total, count in selected) / sum(count for total, count in selected))
    samples.sort()
    return {
        'difference': sum(total for total, count in cells) / sum(count for total, count in cells),
        'lower': samples[int(.025 * repetitions)],
        'upper': samples[int(.975 * repetitions)],
        'schools': len(cells),
    }


def error_share(rows, method, threshold, standardized=False):
    """明確區分原始加權總分與倍率標準化誤差容差。"""
    if not rows:
        raise ValueError('誤差容差集合為空')
    errors = [abs(row[method] - row['actual']) / (row['weightTotal'] if standardized else 1) for row in rows]
    return sum(value <= threshold for value in errors) / len(errors)


def build_results(rows):
    common = common_rows(rows, METHODS)
    pairs = common_rows(rows, ('v3', 'baseline'))
    own = {method: metrics(common_rows(rows, (method,)), method) for method in METHODS}
    ablation = {method: {**metrics(common, method),
                         'quota_mae': metrics(common, method, 'official_quota')['mae'],
                         'applicant_mae': metrics(common, method, 'applicant_count')['mae']}
                for method in METHODS}
    differences = {method: clustered_difference(common, 'v3', method) for method in METHODS if method != 'v3'}
    thresholds = []
    for threshold in (0, 10, 20, 40, 80):
        selected = [row for row in pairs if row['applicant_count'] >= threshold]
        thresholds.append({'threshold': threshold, 'coverage': len(selected) / len(rows),
                           'v3': metrics(selected, 'v3'), 'baseline': metrics(selected, 'baseline'),
                           'difference': clustered_difference(selected, 'v3', 'baseline')})
    missing_history = [row for row in rows if row['no_history_in_snapshot']]
    supported = common_rows(missing_history, ('v3',))
    subgroups = {}
    for label, predicate in [('all', lambda row: True), ('normal', lambda row: row['confidence'] == 'normal'),
                             ('less20', lambda row: row['applicant_count'] < 20),
                             ('atleast20', lambda row: row['applicant_count'] >= 20)]:
        selected = [row for row in supported if predicate(row)]
        subgroups[label] = {**metrics(selected, 'v3'),
                           'raw_within5': error_share(selected, 'v3', 5),
                           'raw_within10': error_share(selected, 'v3', 10),
                           'standardized_within5': error_share(selected, 'v3', 5, True)}
    replay = common_rows(rows, ('v3', 'archived_v3'))
    deltas = [abs(row['v3'] - row['archived_v3']) for row in replay]
    unchanged = [row for row in common if row['unchangedWeights']]
    return {'market': len(rows), 'schools': len({row['school'] for row in rows}),
            'common_n': len(common), 'common_schools': len({row['school'] for row in common}),
            'own': own, 'ablation': ablation, 'differences': differences,
            'pairs_n': len(pairs), 'pairs_difference': clustered_difference(pairs, 'v3', 'baseline'),
            'pairs_v3': metrics(pairs, 'v3'), 'pairs_baseline': metrics(pairs, 'baseline'),
            'pairs_archived_v3': metrics(pairs, 'archived_v3'), 'thresholds': thresholds,
            'unchanged': {method: metrics(unchanged, method) for method in METHODS},
            'no_history_population': len(missing_history), 'no_history_supported': len(supported),
            'no_history_coverage': len(supported) / len(missing_history),
            'no_history_record_absent': sum(row['prior_record_count'] == 0 for row in missing_history),
            'no_history_subgroups': subgroups,
            'replay': {'n': len(deltas), 'mean_abs': statistics.mean(deltas), 'max_abs': max(deltas),
                       'within_half_cent': sum(delta <= .005000001 for delta in deltas)}}


def format_report(result):
    lines = ['# 本輪統計重算結果', '', '最後更新日期：2026-11-25', '',
             '固定校系彙總資料；無個人資料查詢、無重新執行 DA；重抽 4,000 次、種子 20260922。', '',
             f"評估母群 {result['market']} 系／{result['schools']} 校；五方法共同 {result['common_n']} 系／{result['common_schools']} 校。", '',
             '| 方法 | 可估計數 | 各自集合 MAE | 共同 MAE | 偏差 | 名額加權 MAE | 選填加權 MAE | 原始 MAE |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for method in METHODS:
        own, common = result['own'][method], result['ablation'][method]
        lines.append(f"| {method} | {own['n']} | {own['mae']:.4f} | {common['mae']:.4f} | {common['bias']:+.4f} | {common['quota_mae']:.4f} | {common['applicant_mae']:.4f} | {common['raw_mae']:.4f} |")
    lines += ['', '## 五方法共同集合差值', '', '| v3 減比較方法 | 點差 | 敏感度區間 |', '|---|---:|---|']
    for method, values in result['differences'].items():
        lines.append(f"| {method} | {values['difference']:+.4f} | [{values['lower']:+.4f}, {values['upper']:+.4f}] |")
    lines += ['', '## 雙方法共同集合與樣本支援度', '',
              '| 最低選填人數 | 系數 | 學校數 | 涵蓋率 | v3 MAE | 歷史 MAE | 點差 | 敏感度區間 |',
              '|---|---:|---:|---:|---:|---:|---:|---|']
    for row in result['thresholds']:
        values = row['difference']
        lines.append(f"| {row['threshold']} | {row['v3']['n']} | {values['schools']} | {row['coverage']:.1%} | {row['v3']['mae']:.4f} | {row['baseline']['mae']:.4f} | {values['difference']:+.4f} | [{values['lower']:+.4f}, {values['upper']:+.4f}] |")
    lines += ['', '## 歷史門檻缺失子群', '',
              f"歷史範圍限定封存 DB 的 2024／2025：母群 {result['no_history_population']}，模擬有值 {result['no_history_supported']}，涵蓋率 {result['no_history_coverage']:.1%}。", '',
              '| 子群 | 系數 | 標準化 MAE | 原始 MAE | 原始誤差 ≤5 | 原始誤差 ≤10 | 標準化誤差 ≤5 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for label, row in result['no_history_subgroups'].items():
        lines.append(f"| {label} | {row['n']} | {row['mae']:.4f} | {row['raw_mae']:.4f} | {row['raw_within5']:.1%} | {row['raw_within10']:.1%} | {row['standardized_within5']:.1%} |")
    lines += ['', '## 採計項與倍率未變子群', '', '| 方法 | 系數 | MAE |', '|---|---:|---:|']
    for method, row in result['unchanged'].items():
        lines.append(f"| {method} | {row['n']} | {row['mae']:.4f} |")
    replay = result['replay']
    lines += ['', '## 封存值一致性', '',
              f"{replay['n']} 系；平均絕對差 {replay['mean_abs']:.6f}；最大差 {replay['max_abs']:.6f}；≤0.005 分者 {replay['within_half_cent']} 系。", '',
              f"雙方法共同集合封存 v3 MAE：{result['pairs_archived_v3']['mae']:.6f}。", '',
              '區間分位数沿用既有脚本排序後的 0-based 索引 100 與 3900，不採線性內插。']
    return '\n'.join(lines).replace('分位数', '分位數').replace('脚本', '腳本') + '\n'


if __name__ == '__main__':
    result = build_results(load_rows())
    report = format_report(result)
    output_path('results.md').write_text(report, encoding='utf-8')
    output_path('analysis-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(report)
