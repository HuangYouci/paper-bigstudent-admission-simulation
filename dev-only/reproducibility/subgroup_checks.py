"""Detection and combination by applicant-relevant groups (exploratory; added after a second review).

Groups the 1,521 departments of J2 by subject track (Advanced Subjects Test subjects in the 2026
rule: physics, chemistry or biology; history, geography or civics; neither), by historical level, and
by sector, and reports for each group the direction agreement, precision and recall of hot and cold
flags, the share of flagged departments that moved at least one grade the other way, the rank
correlation of S and D, and the combination's gain. It also reports how often a department flagged
cold had an official cutoff at least one grade above the v3 prediction or the combination
("false safety"). Writes subgroup-checks.json.
"""
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, load_rows, common_rows, output_path  # noqa: E402
from demand_signal import spearman  # noqa: E402

DELTA = 1.0
LAMBDA = 0.4
SCIENCE = {'ast_physics', 'ast_chemistry', 'ast_biology'}
HUMANITIES = {'ast_history', 'ast_geography', 'ast_civics'}


def track(items):
    subjects = {i['subject'] for i in items}
    if subjects & SCIENCE and not subjects & HUMANITIES:
        return 'science'
    if subjects & HUMANITIES and not subjects & SCIENCE:
        return 'humanities'
    if subjects & SCIENCE and subjects & HUMANITIES:
        return 'both'
    return 'neither'


def summary(rows):
    d = [(r['actual'] - r['baseline']) / r['weightTotal'] for r in rows]
    s = [(r['v3'] - r['baseline']) / r['weightTotal'] for r in rows]
    hot_f = [k for k, v in enumerate(s) if v >= DELTA]
    cold_f = [k for k, v in enumerate(s) if v <= -DELTA]
    flagged = hot_f + cold_f
    agree = [k for k in flagged if d[k] != 0]
    mix_gain = statistics.fmean(
        (abs(LAMBDA * (r['v3'] - r['actual']) + (1 - LAMBDA) * (r['baseline'] - r['actual'])) - abs(r['baseline'] - r['actual']))
        / r['weightTotal'] for r in rows)
    frac = lambda num, den: num / den if den else None
    return {
        'n': len(rows),
        'flagged': len(flagged),
        'direction_agreement': frac(sum((s[k] > 0) == (d[k] > 0) for k in agree), len(agree)),
        'hot_flags': len(hot_f), 'hot_precision': frac(sum(d[k] >= DELTA for k in hot_f), len(hot_f)),
        'hot_recall': frac(sum(d[k] >= DELTA for k in hot_f), sum(v >= DELTA for v in d)),
        'cold_flags': len(cold_f), 'cold_precision': frac(sum(d[k] <= -DELTA for k in cold_f), len(cold_f)),
        'cold_recall': frac(sum(d[k] <= -DELTA for k in cold_f), sum(v <= -DELTA for v in d)),
        'opposite_share': frac(sum(d[k] <= -DELTA for k in hot_f) + sum(d[k] >= DELTA for k in cold_f), len(flagged)),
        'spearman_S_D': spearman(s, d) if len(rows) > 2 else None,
        'mix_minus_baseline': mix_gain,
        'mae_baseline': statistics.fmean(abs(r['baseline'] - r['actual']) / r['weightTotal'] for r in rows),
        'cold_flag_false_safety_v3': frac(sum((rows[k]['actual'] - rows[k]['v3']) / rows[k]['weightTotal'] >= DELTA for k in cold_f), len(cold_f)),
        'cold_flag_false_safety_mix': frac(sum((rows[k]['actual'] - (LAMBDA * rows[k]['v3'] + (1 - LAMBDA) * rows[k]['baseline']))
                                               / rows[k]['weightTotal'] >= DELTA for k in cold_f), len(cold_f)),
    }


def main():
    rows = load_rows()
    j2 = common_rows(rows, ('v3', 'baseline'))
    items = {d['gid']: d['items'] for d in json.loads((PAPER / 'data/baseline-inputs.json').read_text())['departments']}
    out = {'note': 'exploratory; added after a second pre-submission review', 'n_J2': len(j2), 'delta': DELTA,
           'all': summary(j2), 'track': {}, 'level': {}, 'sector': {}}
    for name in ('science', 'humanities', 'both', 'neither'):
        sub = [r for r in j2 if track(items[r['gid']]) == name]
        if sub:
            out['track'][name] = summary(sub)
    for lo, hi in ((0, 30), (30, 40), (40, 45), (45, 50), (50, 61)):
        sub = [r for r in j2 if lo <= r['baseline'] / r['weightTotal'] < hi]
        out['level'][f'{lo}-{min(hi, 60)}'] = summary(sub)
    public = lambda r: r['school'].startswith(('國立', '臺北市立', '高雄市立', '市立'))
    out['sector']['public'] = summary([r for r in j2 if public(r)])
    out['sector']['private'] = summary([r for r in j2 if not public(r)])
    output_path('subgroup-checks.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
