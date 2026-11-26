"""由公開彙總輸入重建既有同分位基準；不使用考生資料或網路。"""
from pathlib import Path
import csv
import hashlib
import json
import math

PAPER = Path(__file__).resolve().parents[2]


def curve(rows):
    """依平台的離散中點 PR 規格建構曲線，保留零人數級分。"""
    if len(rows) < 2:
        return None
    total = rows[-1]['cum_below']
    if not math.isfinite(total) or total <= 0:
        return None
    return [(r['level'], ((r['cum_below'] - r['people'] / 2) / total) * 100) for r in rows]


def score_at_pr(points, pr):
    """線性反查離散 PR；外側夾端點，平坦段取上界。"""
    if points is None:
        return None
    if pr <= points[0][1]:
        return points[0][0]
    if pr >= points[-1][1]:
        return points[-1][0]
    for (lo, lo_pr), (hi, hi_pr) in zip(points, points[1:]):
        if lo_pr <= pr <= hi_pr:
            if hi_pr == lo_pr:
                return hi
            return lo + (pr - lo_pr) / (hi_pr - lo_pr) * (hi - lo)
    return points[-1][0]


def weighted_score(items, year, pr, distributions):
    total = 0
    for item in items:
        if item['weight'] <= 0:
            continue
        level = score_at_pr(distributions.get(f"{year}:{item['subject']}"), pr)
        if level is None:
            return None
        total += item['weight'] * (level * 4 if item['kind'] == 'gsat60' else level)
    return total


def weighted_pr(items, year, target, distributions):
    minimum = weighted_score(items, year, 0, distributions)
    maximum = weighted_score(items, year, 100, distributions)
    if minimum is None or maximum is None:
        return None
    if target <= minimum:
        return 0
    if target >= maximum:
        return 100
    lo, hi = 0, 100
    for _ in range(60):
        mid = (lo + hi) / 2
        value = weighted_score(items, year, mid, distributions)
        if value < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def prediction(department, distributions):
    old = department['prior']
    if old is None or old['cutoff'] is None or old['hasSkill']:
        return None
    pr = weighted_pr(old['items'], 2025, old['cutoff'], distributions)
    return None if pr is None else weighted_score(department['items'], 2026, pr, distributions)


def main():
    inputs = json.loads((PAPER / 'data/baseline-inputs.json').read_text())
    rows = list(csv.DictReader((PAPER / 'data/department-benchmark.csv').open(newline='')))
    expected = {int(r['gid']): float(r['baseline']) if r['baseline'] else None for r in rows}
    distributions = {key: curve(value) for key, value in inputs['distributions'].items()}
    differences, with_gsat, missing = [], 0, 0
    for d in inputs['departments']:
        result = prediction(d, distributions)
        if (result is None) != (expected[d['gid']] is None):
            raise ValueError('基準缺值型態不一致')
        if result is None:
            missing += 1
            continue
        differences.append(abs(result - expected[d['gid']]))
        with_gsat += int(any(i['kind'] == 'gsat60' for i in d['items']))
    if len(expected) != len(inputs['departments']) or max(differences) > 1e-10:
        raise ValueError('基準數值重建不一致')
    output = {'recordDate': '2026-10-10', 'departments': len(expected), 'predictions': len(differences),
              'missing': missing, 'predictionsUsingGsat': with_gsat, 'maximumAbsoluteDifference': max(differences),
              'inputSHA256': hashlib.sha256((PAPER / 'data/baseline-inputs.json').read_bytes()).hexdigest(),
              'scope': '重現固定比較器，不宣稱學測15級乘四符合正式60級分換算，也不更換既有基準。'}
    (PAPER / 'data/baseline-reconstruction.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
