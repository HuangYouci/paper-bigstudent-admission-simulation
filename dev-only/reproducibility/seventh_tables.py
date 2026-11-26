"""Build Tables 5 and 6 of the manuscript (v0.26) and Tables S33a-S33d and S34 of the supplement from the stored outputs
(seventh-review.json, sixth-review.json, decision-checks.json, revision-checks.json). Writes out/seventh-tables.md.
"""
import json
from pathlib import Path

PAPER = Path(__file__).resolve().parents[2]


def load(name):
    fresh = PAPER / 'out' / name
    return json.loads((fresh if fresh.exists() else PAPER / 'data' / name).read_text())


def g(x):
    s = f'{x:+.2f}'
    return '+0.00' if s == '-0.00' else s.replace('-', '\u2212')


def iv(a, b):
    return f'[{g(a)}, {g(b)}]'


def pct(x, digits=0):
    return f'{100 * x:.{digits}f}%'.replace('-', '\u2212')


def spct(x, digits=1):
    s = f'{100 * x:+.{digits}f}%'
    return s.replace('-', '\u2212') if not s.startswith('+0.0') or digits else s


def main():
    sv = load('seventh-review.json')
    dc = load('decision-checks.json')['decision']['all']['combination_minus_historical']['mae']
    rev = load('revision-checks.json')
    lines = []

    # Table 5.
    order = ('subjects changed', 'multipliers changed alone', 'rules and quota unchanged',
             'rules unchanged, quota change above 0 and at most 0.05', 'rules unchanged, quota change 0.05-0.35',
             'rules unchanged, quota change above 0.35')
    names = {'subjects changed': 'Subjects changed', 'multipliers changed alone': 'Multipliers alone changed',
             'rules and quota unchanged': 'Rules and quota unchanged',
             'rules unchanged, quota change above 0 and at most 0.05': 'Rules unchanged, quota change above 0, at most 0.05',
             'rules unchanged, quota change 0.05-0.35': 'Rules unchanged, quota change 0.05–0.35',
             'rules unchanged, quota change above 0.35': 'Rules unchanged, quota change above 0.35'}
    t5 = sv['table5']
    comp = sv['quota_adjusted']['comparisons']
    lines += ['**Table 5 What the simulation adds, by kind of change, against three history-based predictions**', '',
              '| Departments | Count | Against converted history (planned baseline) | Against quota-adjusted history | Against the production engine | Share of gain against converted history |',
              '|---|---:|---|---|---|---|',
              f"| All of $\\mathcal J_2$ | 1,521 | {g(dc['difference'])} {iv(*dc['interval'])} | {g(comp['combination_vs_quota_adjusted']['gain'])} {iv(*comp['combination_vs_quota_adjusted']['percentile'])} | {g(comp['combination_vs_engine']['gain'])} {iv(*comp['combination_vs_engine']['percentile'])} | 100% |"]
    for k in order:
        b, q, e = t5['baseline']['groups'][k], t5['quota_adjusted']['groups'][k], t5['engine']['groups'][k]
        lines.append(f"| {names[k]} | {b['n']:,} | {g(b['gain'])} {iv(*b['percentile'])} | {g(q['gain'])} {iv(*q['percentile'])} | "
                     f"{g(e['gain'])} {iv(*e['percentile'])} | {pct(b['share_of_total_gain'])} [{pct(b['share_interval'][0])}, {pct(b['share_interval'][1])}] |")
    crit = [t5[c]['critical_value'] for c in ('baseline', 'quota_adjusted', 'engine')]
    lines += ['', f"Note. Gain: the combination's MAE minus the comparator's, in grades (comparator MAE 1.60, {sv['quota_adjusted']['mae']['eQ']:.2f}, and {sv['quota_adjusted']['mae']['eE']:.2f}). "
              'Quota change is the absolute log ratio of the 2026 to the 2025 quota; the groups partition $\\mathcal J_2$, and the department without a 2025 quota is among those whose subjects changed. '
              'Brackets give institution-cluster sensitivity intervals, which for the groups come from one set of 4,000 resamples; '
              f"simultaneous (sup-t) intervals over the six groups, with critical values {min(crit):.2f}–{max(crit):.2f}, are in Supplement S33. "
              'Exploratory: the first entry is the planned comparison; the groups were defined in plan v0.25 after the results for rule changes were known, two of its bins were merged after computation, and the last three columns were added after the seventh simulated review.', '']

    # Table 6.
    t6 = sv['table6']
    old = {r['name']: r for r in rev.get('table6_rows', [])} if isinstance(rev.get('table6_rows'), list) else {}
    rows6 = (('level 0-30', 'Level 0–30'), ('level 30-40', 'Level 30–40'), ('level 40-45', 'Level 40–45'), ('level 45-50', 'Level 45–50'),
             ('level 50-60', 'Level 50–60'), ('level 0-30, north', 'Level 0–30, north'), ('level 0-30, central', 'Level 0–30, central'),
             ('level 0-30, south', 'Level 0–30, south'), ('level 0-30, east_and_kinmen', 'Level 0–30, east and Kinmen'))
    lines += ['TABLE6_ROWS (gain columns)', '']
    for k, label in rows6:
        b, q, e = t6['baseline']['groups'][k], t6['quota_adjusted']['groups'][k], t6['engine']['groups'][k]
        if b['institutions'] >= 5:
            lines.append(f"| {label} | {b['n']} ({b['institutions']}) | {g(b['gain'])} {iv(*b['percentile'])} | {iv(*b['simultaneous'])} | "
                         f"{g(q['gain'])} {iv(*q['percentile'])} | {g(e['gain'])} {iv(*e['percentile'])} |")
        else:
            lines.append(f"| {label} | {b['n']} ({b['institutions']}) | {g(b['gain'])} | — | {g(q['gain'])} | {g(e['gain'])} |")
    lines += ['', f"Table 6 critical values: baseline {t6['baseline']['critical_value']:.2f}, quota-adjusted {t6['quota_adjusted']['critical_value']:.2f}, engine {t6['engine']['critical_value']:.2f}", '']

    # Table S33a: simultaneous intervals for Table 5.
    lines += ['**Table S33a Simultaneous intervals for the groups of Table 5**', '',
              '| Group | Against converted history | Against quota-adjusted history | Against the engine | Same weight on quota-adjusted history | Backtest rule with the engine |',
              '|---|---|---|---|---|---|']
    for k in order:
        cells = []
        for c in ('baseline', 'quota_adjusted', 'engine', 'quota_adjusted_reanchored', 'engine_august_rule'):
            v = t5[c]['groups'][k]
            cells.append(f"{g(v['gain'])} {iv(*v['simultaneous'])}")
        lines.append(f"| {names[k]} | " + ' | '.join(cells) + ' |')
    lines.append('| Critical value | ' + ' | '.join(f"{t5[c]['critical_value']:.2f}" for c in ('baseline', 'quota_adjusted', 'engine', 'quota_adjusted_reanchored', 'engine_august_rule')) + ' |')
    lines.append('')

    # Table S33b: transport.
    tr = sv['transport']
    lines += ['**Table S33b The gain reweighted to the 2024–2025 composition of changes**', '',
              '| Group | Departments, 2024–2025 | Share, 2024–2025 | Share, 2026 ($\\mathcal J_2$) |', '|---|---:|---:|---:|']
    for k in ('rules changed', 'rules and quota unchanged', 'quota change at most 0.05', 'quota change 0.05-0.35', 'quota change above 0.35'):
        c = tr['composition_2025'][k]
        lines.append(f"| {k.replace('0.05-0.35', '0.05–0.35')} | {c['departments']:,} | {pct(c['share'], 1)} | {pct(c['share_2026_J2'], 1)} |")
    lines += ['', '| Departments and comparator | Gain, 2026 composition | Gain, 2024–2025 composition [interval] |', '|---|---|---|']
    for k in ('all vs baseline', 'all vs quota_adjusted', 'all vs engine', 'rules unchanged vs baseline', 'rules unchanged vs quota_adjusted',
              'rules unchanged vs engine', 'rules and quota unchanged vs baseline'):
        v = tr[k]
        lines.append(f"| {k.replace('_', '-')} | {g(v['gain_2026_composition'])} ({pct(v['relative_2026_composition'], 1)}) | {g(v['gain_2025_composition'])} ({pct(v['relative_2025_composition'], 1)}) {iv(*v['interval'])} |")
    lines.append('')

    # Table S33c: common shift by group.
    sh = sv['shift_by_group']
    lines += ['**Table S33c Relative gain if every error moved by the same amount, by group**', '',
              '| Group | −1.17 | −0.58 | 0 | +0.58 | +1.17 |', '|---|---|---|---|---|---|']
    zero = {k: t5['baseline']['groups'][k]['relative'] for k in order}
    for k in order:
        lines.append(f"| {names[k]} | " + ' | '.join(spct(sh[c][k]['relative_vs_baseline']) if c != '0' else spct(zero[k])
                                                      for c in ('-1.17', '-0.58', '0', '+0.58', '+1.17')) + ' |')
    for key, label in (('relative_vs_baseline', 'All, against converted history'), ('relative_vs_quota_adjusted', 'All, against quota-adjusted history'),
                       ('relative_reanchored_vs_quota_adjusted', 'All, same weight on quota-adjusted history'), ('relative_vs_engine', 'All, against the engine')):
        base0 = {'relative_vs_baseline': comp['combination_vs_baseline']['relative'], 'relative_vs_quota_adjusted': comp['combination_vs_quota_adjusted']['relative'],
                 'relative_reanchored_vs_quota_adjusted': comp['reanchored_vs_quota_adjusted']['relative'], 'relative_vs_engine': comp['combination_vs_engine']['relative']}[key]
        lines.append(f"| {label} | " + ' | '.join(spct(sh[c]['all'][key]) if c != '0' else spct(base0) for c in ('-1.17', '-0.58', '0', '+0.58', '+1.17')) + ' |')
    lines.append('')

    # Table S34: multiplicity.
    lines += ['**Table S34b Bootstrap p-values of the subgroup gains of Tables 5 and 6, with Holm and Benjamini–Hochberg adjustment**', '',
              '| Group | Against converted history: p / Holm / BH | Against quota-adjusted history: p / Holm / BH |', '|---|---|---|']
    mb, mq = sv['multiplicity'], sv['multiplicity_quota_adjusted']
    for k in sorted(mb, key=lambda x: mb[x]['p']):
        f = lambda d: f"{d['p']:.3f} / {d['holm']:.3f} / {d['bh']:.3f}"
        lines.append(f"| {k.replace('east_and_kinmen', 'east and Kinmen').replace('-', '–')} | {f(mb[k])} | {f(mq[k])} |")
    out = PAPER / 'out'
    out.mkdir(exist_ok=True)
    (out / 'seventh-tables.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(out / 'seventh-tables.md')


if __name__ == '__main__':
    main()
