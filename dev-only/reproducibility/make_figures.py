"""Draw the manuscript figures (overview, demand, timeline), the supplementary chart by minimum listings (coverage)
and the five-method ablation chart from the stored outputs.

Reads analysis-results.json, decision-checks.json, demand-signal-results.json, seventh-review.json,
author-checks.json, author-checks-round6.json, author-stats.json and archived-run-results.json (from out/ if present,
else data/) and the controlled-tier department file, and writes out/figures/{overview,ablation,coverage,demand,
timeline}.{svg,png}; with WRITE_REFERENCE=1 it reads data/ and writes the stored figures/.
Requires ReportLab; PNG output also requires rlPyCairo (pip install reportlab rlPyCairo).
"""
import csv
import json
import os
import sys
from pathlib import Path

from reportlab.graphics import renderPM, renderSVG
from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, clustered_difference, common_rows, input_path, load_rows  # noqa: E402

REFERENCE = os.environ.get('WRITE_REFERENCE') == '1'
GREEK = 'GreekSerif'
for candidate in ('/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf', '/System/Library/Fonts/Supplemental/Times New Roman.ttf'):
    if Path(candidate).exists():
        pdfmetrics.registerFont(TTFont(GREEK, candidate))
        break
else:
    GREEK = None


def label_with_lambda(drawing, x, y, before, after, size=10):
    """Centered label with a Greek lambda between two Times strings, matching the other labels."""
    glyph, font = ('λ', GREEK) if GREEK else ('lambda', 'Times-Roman')
    w1 = pdfmetrics.stringWidth(before, 'Times-Roman', size)
    w2 = pdfmetrics.stringWidth(glyph, font, size)
    w3 = pdfmetrics.stringWidth(after, 'Times-Roman', size)
    x0 = x - (w1 + w2 + w3) / 2
    drawing.add(String(x0, y, before, fontSize=size, fontName='Times-Roman'))
    drawing.add(String(x0 + w1, y, glyph, fontSize=size, fontName=font))
    drawing.add(String(x0 + w1 + w2, y, after, fontSize=size, fontName='Times-Roman'))
FIGURES = PAPER / 'figures' if REFERENCE else PAPER / 'out' / 'figures'


def results(name):
    fresh = PAPER / 'out' / name
    return fresh if fresh.exists() and not REFERENCE else PAPER / 'data' / name


results_path = results


def write(drawing, name):
    FIGURES.mkdir(exist_ok=True)
    renderSVG.drawToFile(drawing, str(FIGURES / (name + '.svg')))
    renderPM.drawToFile(drawing, str(FIGURES / (name + '.png')), fmt='PNG', dpi=300)


def ablation(results):
    """Supplementary chart: MAE of the five methods on the common departments."""
    drawing = Drawing(500, 235)
    chart = HorizontalBarChart()
    chart.x, chart.y, chart.width, chart.height = 90, 40, 345, 175
    keys = ['baseline', 'v3', 'fractional', 'v2', 'v1']
    chart.data = [[results['ablation'][key]['mae'] for key in keys]]
    chart.categoryAxis.categoryNames = ['Historical', 'v3', 'Fractional', 'v2', 'v1']
    chart.categoryAxis.labels.fontName = 'Helvetica'
    chart.categoryAxis.labels.fontSize = 10
    chart.valueAxis.valueMin, chart.valueAxis.valueMax, chart.valueAxis.valueStep = 0, 3.6, 1
    chart.valueAxis.labels.fontSize = 10
    chart.bars[0].fillColor = colors.HexColor('#777777')
    chart.bars[0].strokeColor = None
    chart.barLabelFormat = None
    drawing.add(chart)
    for index, key in enumerate(keys):
        value = results['ablation'][key]['mae']
        x = chart.x + value / chart.valueAxis.valueMax * chart.width + 6
        y = chart.y + (index + 0.5) * chart.height / len(keys) - 3
        drawing.add(String(x, y, f'{value:.2f}', fontSize=10, textAnchor='start'))
    drawing.add(String(240, 10, f"Multiplier-standardized MAE ({results['common_n']:,} common departments)",
                       fontSize=10, textAnchor='middle'))
    write(drawing, 'ablation')


def overview():
    """Figure 1: the fixed combination's MAE difference from three history-based comparators, in reruns that change one
    input, on records saved before the deadline, and by the number of listings, with institution-cluster intervals."""
    dc = json.loads(results('decision-checks.json').read_text())['decision']['all']['combination_minus_historical']['mae']
    sv = json.loads(results('seventh-review.json').read_text())
    comp = sv['quota_adjusted']['comparisons']
    r6 = json.loads(results('author-checks-round6.json').read_text())
    labels = json.loads(results('author-stats.json').read_text())['groups']['runs']['labels']
    saved = json.loads(results('archived-run-results.json').read_text())['lastOutputBeforeDeadline']['mix_minus_baseline']
    frac = sv['fractional']['gain']
    rows = load_rows()
    j2 = common_rows(rows, ('v3', 'baseline'))
    for r in j2:
        r['mix'] = 0.4 * r['v3'] + 0.6 * r['baseline']
    bins = []
    for lo, hi, name in ((5, 10, '5–9'), (10, 20, '10–19'), (20, 40, '20–39'), (40, 80, '40–79'), (80, 10 ** 9, '80 or more')):
        s = [r for r in j2 if lo <= r['applicant_count'] < hi]
        d = clustered_difference(s, 'mix', 'baseline')
        bins.append((f'{name} listings ({len(s):,})', d['difference'], (d['lower'], d['upper'])))
    pick = lambda c: (c['gain'], tuple(c['percentile']))
    blocks = [
        ('Evaluated run, 1,521 departments: combination minus', [
            ('planned baseline (converted history)', dc['difference'], tuple(dc['interval'])),
            ('history adjusted for announced quotas', *pick(comp['combination_vs_quota_adjusted'])),
            ('production engine (reconstructed)', *pick(comp['combination_vs_engine'])),
            ('same weight on quota-adjusted history, minus it', *pick(comp['reanchored_vs_quota_adjusted'])),
            ('backtest rule with the engine, minus the engine', *pick(comp['august_rule_vs_engine']))]),
        ('Rerun on the evaluated records, minus planned baseline', [
            ('2025 quotas instead of 2026', r6['quota2025']['quota_2025']['gain'], tuple(r6['quota2025']['quota_2025']['gain_interval'])),
            ('lists generated from public information', r6['synthetic']['generated_lists_own_length']['gain'],
             tuple(r6['synthetic']['generated_lists_own_length']['gain_interval'])),
            ("each account's earliest saved list", r6['earliest']['earliest_lists']['gain'], tuple(r6['earliest']['earliest_lists']['gain_interval'])),
            ('Fractional in place of v3', frac['gain'], tuple(frac['percentile']))]),
        ('Records saved before the deadline, minus planned baseline', [
            ('v3 rerun on the run of 8 Aug 12:01', labels['run-ast_20260808T035958Z']['combination_minus_baseline']['difference'],
             tuple(labels['run-ast_20260808T035958Z']['combination_minus_baseline']['interval'])),
            ('v3 rerun on the deadline reconstruction', labels['deadline-reconstructed']['combination_minus_baseline']['difference'],
             tuple(labels['deadline-reconstructed']['combination_minus_baseline']['interval'])),
            ('output saved at 12:01 (deployed v2; 1,389)', saved['difference'], tuple(saved['interval']))]),
        ('Evaluated run by listings, minus planned baseline', bins)]
    n_rows = sum(len(b) for _, b in blocks)
    height = 46 + n_rows * 14 + len(blocks) * 17
    drawing = Drawing(500, height)
    x0, x1, lo, hi = 262, 490, -0.75, 0.22

    def x(v):
        return x0 + (max(min(v, hi), lo) - lo) / (hi - lo) * (x1 - x0)
    drawing.add(Line(x0, 30, x1, 30))
    for t in (-0.6, -0.4, -0.2, 0.0, 0.2):
        drawing.add(Line(x(t), 27, x(t), 30))
        drawing.add(String(x(t), 16, f'{t:+.1f}' if t else '0', fontSize=8.5, textAnchor='middle'))
    drawing.add(String((x0 + x1) / 2, 3, 'MAE difference in grades (negative favors the combination)', fontSize=9, textAnchor='middle'))
    top = height - 8
    drawing.add(Line(x(0), 30, x(0), top, strokeColor=colors.gray, strokeDashArray=[3, 3], strokeWidth=0.6))
    y = top
    for title, items in blocks:
        y -= 13
        drawing.add(String(4, y, title, fontSize=8.5, fontName='Times-Bold'))
        for label, est, (a, b) in items:
            y -= 14
            drawing.add(String(12, y - 3, label, fontSize=8.5))
            drawing.add(Line(x(a), y, x(b), y, strokeWidth=1))
            for end in (a, b):
                drawing.add(Line(x(end), y - 3, x(end), y + 3, strokeWidth=0.8))
            drawing.add(Circle(x(est), y, 2.8, fillColor=colors.black))
            if a < lo:
                drawing.add(String(x0 - 9, y - 3, '←', fontSize=8))
            if b > hi:
                drawing.add(String(x1 + 2, y - 3, '→', fontSize=8))
        y -= 4
    write(drawing, 'overview')


def coverage(results):
    """Figure 1: v3 minus historical MAE by minimum number of platform listings."""
    drawing = Drawing(500, 225)
    x0, x1, lo, hi = 95, 365, -0.2, 0.42

    def x(value):
        return x0 + (value - lo) / (hi - lo) * (x1 - x0)
    drawing.add(Line(x0, 35, x1, 35, strokeColor=colors.black))
    for tick in (-0.2, 0, 0.2, 0.4):
        drawing.add(Line(x(tick), 32, x(tick), 35))
        drawing.add(String(x(tick), 19, f'{tick:.1f}', fontSize=10, textAnchor='middle'))
    drawing.add(Line(x(0), 35, x(0), 196, strokeColor=colors.gray, strokeDashArray=[3, 3]))
    drawing.add(String(40, 207, 'Min. listings', fontSize=10, textAnchor='middle'))
    drawing.add(String(442, 207, 'Coverage', fontSize=10, textAnchor='middle'))
    for i, row in enumerate(results['thresholds']):
        y = 184 - i * 32
        value = row['difference']
        drawing.add(String(40, y - 3, str(row['threshold']), fontSize=11, textAnchor='middle'))
        drawing.add(Line(x(value['lower']), y, x(value['upper']), y, strokeWidth=1.2))
        for end in ('lower', 'upper'):
            drawing.add(Line(x(value[end]), y - 4, x(value[end]), y + 4))
        drawing.add(Circle(x(value['difference']), y, 3.5, fillColor=colors.black))
        drawing.add(String(442, y - 3, f"{row['coverage'] * 100:.1f}%", fontSize=11, textAnchor='middle'))
    drawing.add(String(230, 3, 'MAE difference: v3 minus historical baseline', fontSize=10, textAnchor='middle'))
    write(drawing, 'coverage')


def demand(results):
    """Figure 2: (A) MAE against the combination weight, with the production engine's MAE for reference; (B) observed
    against simulated departure on inverse-hyperbolic-sine axes, with the slope through the origin and the slope that
    the fixed weight implies."""
    import math
    # Panel B plots only departments whose v3 the public tier releases (Supplement S3), so that no withheld value can be
    # read off the figure; the curve in panel A and the slope are computed on all departments of J2.
    from make_public_tier import public_v3
    points, n_all = [], 0
    with input_path('department-benchmark.csv').open(encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            if row['v3'] and row['baseline'] and row['actual']:
                n_all += 1
                if row['fractional'] and not public_v3(row):
                    continue
                b, w = float(row['baseline']), float(row['weightTotal'])
                points.append(((float(row['v3']) - b) / w, (float(row['actual']) - b) / w))
    sv = json.loads(results_path('seventh-review.json').read_text())
    engine_mae = sv['quota_adjusted']['mae']['eE']
    slope = json.loads(results_path('sixth-review.json').read_text())['encompassing']['slope_through_origin']
    drawing = Drawing(500, 262)
    lx0, lx1, ly0, ly1, mlo, mhi = 45, 215, 50, 215, 1.2, 1.9

    def lx(v):
        return lx0 + v * (lx1 - lx0)

    def ly(v):
        return ly0 + (v - mlo) / (mhi - mlo) * (ly1 - ly0)
    drawing.add(Rect(lx(0.36), ly0, lx(0.44) - lx(0.36), ly1 - ly0, fillColor=colors.HexColor('#e6e6e6'), strokeColor=None))
    drawing.add(Line(lx0, ly0, lx1, ly0))
    drawing.add(Line(lx0, ly0, lx0, ly1))
    for t in (0, 0.2, 0.4, 0.6, 0.8, 1.0):
        drawing.add(Line(lx(t), ly0 - 3, lx(t), ly0))
        drawing.add(String(lx(t), ly0 - 14, f'{t:.1f}', fontSize=9, textAnchor='middle'))
    for t in (1.2, 1.4, 1.6, 1.8):
        drawing.add(Line(lx0 - 3, ly(t), lx0, ly(t)))
        drawing.add(String(lx0 - 6, ly(t) - 3, f'{t:.1f}', fontSize=9, textAnchor='end'))
    drawing.add(Line(lx0, ly(engine_mae), lx1, ly(engine_mae), strokeColor=colors.gray, strokeDashArray=[2, 2], strokeWidth=0.7))
    drawing.add(String(lx1 - 2, ly(engine_mae) + 3, f'production engine {engine_mae:.2f}', fontSize=8, textAnchor='end'))
    curve = results['h1_lambda_curve_descriptive']
    for a, b in zip(curve, curve[1:]):
        drawing.add(Line(lx(a['lambda']), ly(a['mae']), lx(b['lambda']), ly(b['mae']), strokeWidth=1.1))
    for c in curve:
        drawing.add(Circle(lx(c['lambda']), ly(c['mae']), 2, fillColor=colors.black, strokeColor=None))
    fixed = next(c for c in curve if abs(c['lambda'] - 0.4) < 1e-9)
    drawing.add(Line(lx(0.4), ly0, lx(0.4), ly(fixed['mae']), strokeColor=colors.gray, strokeDashArray=[3, 3]))
    drawing.add(Circle(lx(0.4), ly(fixed['mae']), 4.5, fillColor=None, strokeColor=colors.black, strokeWidth=1.2))
    drawing.add(String(lx(0.4) + 8, ly(fixed['mae']) - 12, 'fixed in advance (0.4)', fontSize=9))
    drawing.add(String(lx(0) + 3, ly(curve[0]['mae']) + 4, f"history {curve[0]['mae']:.2f}", fontSize=8))
    drawing.add(String(lx(0.96), ly(curve[-1]['mae']) + 2, f"v3 {curve[-1]['mae']:.2f}", fontSize=8, textAnchor='end'))
    drawing.add(Line(lx(0.106), ly0, lx(0.106), ly0 + 6, strokeWidth=1))
    drawing.add(String(lx(0.106), ly0 + 8, '0.106', fontSize=7, textAnchor='middle'))
    label_with_lambda(drawing, (lx0 + lx1) / 2, 18, 'Weight on v3, ', '')
    drawing.add(String((lx0 + lx1) / 2, 246, f'A  MAE on {n_all:,} departments', fontSize=10, textAnchor='middle'))
    drawing.add(String(lx0 - 30, ly1 + 10, 'MAE (grades)', fontSize=9, textAnchor='start'))
    rx0, rx1, ry0, ry1, lim = 290, 480, 50, 215, math.asinh(26)

    def tr(v):
        return math.asinh(v)

    def px(v):
        return rx0 + (tr(v) + lim) / (2 * lim) * (rx1 - rx0)

    def py(v):
        return ry0 + (tr(v) + lim) / (2 * lim) * (ry1 - ry0)
    drawing.add(Rect(rx0, ry0, rx1 - rx0, ry1 - ry0, fillColor=None, strokeColor=colors.black, strokeWidth=0.6))
    drawing.add(Rect(px(-1), ry0, px(1) - px(-1), ry1 - ry0, fillColor=colors.HexColor('#f0f0f0'), strokeColor=None))
    drawing.add(Line(px(0), ry0, px(0), ry1, strokeColor=colors.gray, strokeWidth=0.5))
    drawing.add(Line(rx0, py(0), rx1, py(0), strokeColor=colors.gray, strokeWidth=0.5))
    dot = colors.Color(0.2, 0.2, 0.2, alpha=0.35)
    for s_, d in points:
        drawing.add(Circle(px(s_), py(d), 1.2, fillColor=dot, strokeColor=None))
    for k, dash, width in ((1.0, [3, 3], 0.7), (slope, None, 1.0), (0.4, [1, 2], 1.0)):
        xs = [v / 10 for v in range(-260, 261)]
        pts = []
        for v in xs:
            dv = k * v
            if abs(tr(dv)) <= lim:
                pts += [px(v), py(dv)]
        drawing.add(PolyLine(pts, strokeColor=colors.black if dash is None else colors.gray, strokeWidth=width, strokeDashArray=dash))
    for t in (-16, -4, -1, 0, 1, 4, 16):
        drawing.add(String(px(t), ry0 - 14, str(t), fontSize=9, textAnchor='middle'))
        drawing.add(String(rx0 - 5, py(t) - 3, str(t), fontSize=9, textAnchor='end'))
    drawing.add(String(rx0 + 4, ry1 - 11, f'slope {slope:.2f} (solid)', fontSize=8, textAnchor='start'))
    drawing.add(String((rx0 + rx1) / 2, 18, 'Simulated departure S (grades)', fontSize=10, textAnchor='middle'))
    drawing.add(String((rx0 + rx1) / 2, 246, f'B  Observed against simulated, {len(points):,} departments', fontSize=10, textAnchor='middle'))
    drawing.add(String(rx0 - 22, ry1 + 10, 'Observed departure D (grades)', fontSize=9, textAnchor='start'))
    write(drawing, 'demand')


def timeline(checks, stats):
    """Figure 3: the fixed combination's MAE difference from history (A) for v3 rerun on each saved run's records,
    by completion time, and (B) against the number of records, with the learning curve of random subsamples
    (20 draws at each eighth of the evaluated records: mean and one standard deviation)."""
    from datetime import datetime, timezone, timedelta
    runs = {r['label']: r for r in checks['sections']['runs']['summary']}
    labels = stats['groups']['runs']['labels']
    taiwan = timezone(timedelta(hours=8))
    points = []
    for label, r in runs.items():
        if not label.startswith('run-') or label.endswith('no-zero-cleaning'):
            continue
        done = datetime.fromisoformat(r['run']['completedAt'].replace('Z', '+00:00')).astimezone(taiwan)
        c = labels[label]['combination_minus_baseline']
        points.append((done, r['counts']['effective'], c['difference'], c['interval']))
    points.sort()
    drawing = Drawing(500, 260)
    ylo, yhi = -0.36, 0.2
    ax0, ax1, ay0, ay1 = 52, 228, 45, 210
    start = datetime(2026, 8, 5, 12, tzinfo=taiwan)
    span = (datetime(2026, 8, 16, 12, tzinfo=taiwan) - start).total_seconds()

    def ty(v):
        return ay0 + (v - ylo) / (yhi - ylo) * (ay1 - ay0)

    def tx(t):
        return ax0 + (t - start).total_seconds() / span * (ax1 - ax0)
    for x0_, x1_ in ((ax0, ax1), (290, 480)):
        drawing.add(Line(x0_, ay0, x1_, ay0))
        drawing.add(Line(x0_, ay0, x0_, ay1))
        drawing.add(Line(x0_, ty(0), x1_, ty(0), strokeColor=colors.gray, strokeWidth=0.5))
        for v in (-0.3, -0.2, -0.1, 0.0, 0.1, 0.2):
            drawing.add(Line(x0_ - 3, ty(v), x0_, ty(v)))
            drawing.add(String(x0_ - 5, ty(v) - 3, f'{v:+.1f}' if v else '0', fontSize=9, textAnchor='end'))
    for day in (6, 8, 10, 12, 14, 16):
        t = datetime(2026, 8, day, tzinfo=taiwan)
        drawing.add(Line(tx(t), ay0 - 3, tx(t), ay0))
        drawing.add(String(tx(t), ay0 - 14, f'{day} Aug', fontSize=9, textAnchor='middle'))
    deadline = datetime(2026, 8, 8, 16, 30, tzinfo=taiwan)
    # a: divisible mass written in the research code; b: registration closed; c: the weight committed (the caption explains).
    marks = ((datetime(2026, 8, 7, 22, 31, tzinfo=taiwan), 'a', 'end', -2),
             (deadline, 'b', 'start', 2),
             (datetime(2026, 8, 13, 1, 44, tzinfo=taiwan), 'c', 'start', 2))
    for when, text, anchor, dx in marks:
        drawing.add(Line(tx(when), ay0, tx(when), ay1, strokeColor=colors.gray, strokeDashArray=[3, 3]))
        drawing.add(String(tx(when) + dx, ay1 - 8, text, fontSize=9, textAnchor=anchor))
    for done, n, d, (lo, hi) in points:
        drawing.add(Line(tx(done), ty(lo), tx(done), ty(hi), strokeWidth=1))
        drawing.add(Circle(tx(done), ty(d), 3, fillColor=colors.black if done < deadline else colors.white, strokeColor=colors.black))
    drawing.add(String((ax0 + ax1) / 2, 18, 'Completion time of the saved run (Taiwan)', fontSize=10, textAnchor='middle'))
    drawing.add(String((ax0 + ax1) / 2, 246, 'A  v3 rerun on each saved run', fontSize=10, textAnchor='middle'))
    drawing.add(String(ax0 - 40, ay1 + 12, 'Combination minus historical MAE (grades)', fontSize=9, textAnchor='start'))
    bx0, bx1, nmax = 290, 480, 5000

    def bx(n):
        return bx0 + n / nmax * (bx1 - bx0)
    for n in (0, 1000, 2000, 3000, 4000, 5000):
        drawing.add(Line(bx(n), ay0 - 3, bx(n), ay0))
        drawing.add(String(bx(n), ay0 - 14, f'{n:,}', fontSize=9, textAnchor='middle'))
    levels = checks['sections']['curve']['levels']
    curve = sorted((v['records'], v['mixMinusBaseline']['mean'], v['mixMinusBaseline']['sd']) for v in levels.values())
    final = labels['run-ast_20260815T150000Z']['combination_minus_baseline']['difference']
    curve.append((4627, final, 0.0))
    grey = colors.HexColor('#888888')
    for (n0, m0, _), (n1, m1, _) in zip(curve, curve[1:]):
        drawing.add(Line(bx(n0), ty(m0), bx(n1), ty(m1), strokeColor=grey, strokeWidth=1.2))
    for n, m, sd in curve[:-1]:
        drawing.add(Line(bx(n), ty(m - sd), bx(n), ty(m + sd), strokeColor=grey, strokeWidth=1))
        drawing.add(Rect(bx(n) - 2, ty(m) - 2, 4, 4, fillColor=grey, strokeColor=None))
    for done, n, d, _ in points:
        drawing.add(Circle(bx(n), ty(d), 3, fillColor=colors.black if done < deadline else colors.white, strokeColor=colors.black))
    drawing.add(String((bx0 + bx1) / 2, 18, 'Records in the simulated sample', fontSize=10, textAnchor='middle'))
    drawing.add(String((bx0 + bx1) / 2, 246, 'B  Saved runs and the learning curve', fontSize=10, textAnchor='middle'))
    write(drawing, 'timeline')


def main():
    analysis = json.loads(results('analysis-results.json').read_text())
    overview()
    ablation(analysis)
    coverage(analysis)
    demand(json.loads(results('demand-signal-results.json').read_text()))
    timeline(json.loads(results('author-checks.json').read_text()), json.loads(results('author-stats.json').read_text()))
    print(f'Wrote {FIGURES.relative_to(PAPER)}/overview, ablation, coverage, demand and timeline (.svg and .png).')


if __name__ == '__main__':
    main()
