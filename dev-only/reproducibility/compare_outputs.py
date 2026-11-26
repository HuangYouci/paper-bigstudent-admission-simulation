"""Compare regenerated outputs in out/ with the stored reference outputs in data/.

For each JSON file present in both folders, reports the number of numeric values compared, the number that differ by
more than 1e-9, the largest absolute difference with its key path, and every structural difference: keys present in only
one file, lists of different lengths, and values whose type, finiteness or nullness differs. Exits with status 1 if any
file differs. Every stored output was computed from the released files, so no difference is expected; outputs of steps
that readers cannot rerun (Node scripts, archived_run_summary.py, the author checks) are not regenerated.
"""
import json
import math
import sys
from pathlib import Path

PAPER = Path(__file__).resolve().parents[2]
TOLERANCE = 1e-9


def walk(a, b, path, values, problems):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(a.keys() ^ b.keys()):
            problems.append(f'{path}.{key}: present in only one file')
        for key in sorted(a.keys() & b.keys()):
            walk(a[key], b[key], f'{path}.{key}', values, problems)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            problems.append(f'{path}: lists of length {len(a)} and {len(b)}')
            return
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f'{path}[{i}]', values, problems)
    elif isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str) or isinstance(b, str):
        if a != b:
            problems.append(f'{path}: {a!r} against {b!r}')
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isfinite(a) and math.isfinite(b):
            values.append((abs(a - b), path))
        elif not (math.isnan(a) and math.isnan(b)) and a != b:
            problems.append(f'{path}: {a!r} against {b!r}')
    else:
        problems.append(f'{path}: {type(a).__name__} against {type(b).__name__}')


def main():
    names = sorted(p.name for p in (PAPER / 'out').glob('*.json') if (PAPER / 'data' / p.name).exists())
    if not names:
        raise SystemExit('No outputs in out/ to compare; run the analysis scripts first.')
    failed = False
    for name in names:
        values, problems = [], []
        walk(json.loads((PAPER / 'out' / name).read_text()), json.loads((PAPER / 'data' / name).read_text()), '', values, problems)
        changed = [d for d in values if d[0] > TOLERANCE]
        largest = max(values, default=(0.0, ''))
        print(f'{name}: {len(values)} values, {len(changed)} differ, {len(problems)} structural differences; '
              f'largest difference {largest[0]:.6g} at {largest[1] or "-"}')
        for line in problems[:20]:
            print('   ', line)
        failed = failed or bool(changed or problems)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
