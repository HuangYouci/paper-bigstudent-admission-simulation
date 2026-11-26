"""Coarsen the stored analysis outputs of the public tier (author-side tool, v0.27).

Most stored outputs are statistics on sets of departments that include values the public tier withholds. At full
precision, a statistic on a small set, or on a set with only one withheld department, can be solved for that
department's withheld v3 given the public values of the others. In the public tier, this script therefore
  1. replaces with null every number in a cell that reports fewer than ten departments (keys 'n' or 'departments'),
     and marks the cell "suppressed";
  2. rounds every other floating-point number to two decimal places, or to one significant digit if its magnitude is
     below 0.01, so that the public outputs carry no more precision than the manuscript and supplement.
Files that the public tier itself recomputes (public-checks.json, public-tier.json), official and historical source
audits, the manifest, and outputs on synthetic markets are left unchanged. The controlled tier keeps every output at
full precision, and compare_outputs.py is run against it.

Usage: python3 redact_public_outputs.py DATA_DIR
"""
import json
import math
import sys
from pathlib import Path

UNCHANGED = {
    'public-checks.json', 'public-tier.json', 'manifest.json', 'suppression.json',
    'official-marginal-audit.json', 'official-rules-audit.json', 'official-truth-audit.json',
    'historical-cutoff-audit.json', 'historical-marginal-audit.json', 'baseline-gsat-margin-audit.json',
    'baseline-inputs.json', 'history-inputs.json', 'baseline-reconstruction.json',
    'reference-allocation.json', 'platform-exact.json', 'platform-exact-platform.json',
    'stress-results.json', 'stress-diagnostics.json',
}
COUNT_KEYS = ('n', 'departments')
MIN_DEPARTMENTS = 10


def coarse(x):
    if not math.isfinite(x) or x == 0:
        return x
    if abs(x) >= 0.01:
        return round(x, 2)
    digits = -int(math.floor(math.log10(abs(x))))
    return round(x, digits)


def small_cell(node):
    return any(isinstance(node.get(k), int) and not isinstance(node.get(k), bool) and 0 < node[k] < MIN_DEPARTMENTS
               for k in COUNT_KEYS)


def blank(node):
    if isinstance(node, dict):
        return {k: (v if k in COUNT_KEYS or isinstance(v, (str, bool)) else blank(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [blank(v) for v in node]
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return None
    return node


def redact(node, counts):
    if isinstance(node, dict):
        if small_cell(node):
            counts['suppressed'] += 1
            out = blank(node)
            out['suppressed'] = f'fewer than {MIN_DEPARTMENTS} departments'
            return out
        return {k: redact(v, counts) for k, v in node.items()}
    if isinstance(node, list):
        return [redact(v, counts) for v in node]
    if isinstance(node, float):
        counts['rounded'] += 1
        return coarse(node)
    return node


def main():
    data = Path(sys.argv[1])
    total = {'files': 0, 'suppressed': 0, 'rounded': 0}
    for path in sorted(data.glob('*.json')):
        if path.name in UNCHANGED:
            continue
        counts = {'suppressed': 0, 'rounded': 0}
        out = redact(json.loads(path.read_text(encoding='utf-8')), counts)
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        total['files'] += 1
        total['suppressed'] += counts['suppressed']
        total['rounded'] += counts['rounded']
        if counts['suppressed']:
            print(f"{path.name}: {counts['suppressed']} small cells suppressed")
    manifest = data / 'manifest.json'
    m = json.loads(manifest.read_text(encoding='utf-8'))
    m['publicOutputCoarsening'] = (
        'In the public tier, stored analysis outputs other than public-checks.json, public-tier.json, source audits and '
        'synthetic-market outputs are rounded to two decimal places (one significant digit below 0.01), and cells '
        f'reporting fewer than {MIN_DEPARTMENTS} departments are suppressed, by redact_public_outputs.py; the '
        'controlled tier keeps them at full precision.')
    manifest.write_text(json.dumps(m, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(total)


if __name__ == '__main__':
    main()
