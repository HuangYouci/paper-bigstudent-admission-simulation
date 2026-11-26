"""The platform's frozen divisible-mass function against the exact textbook procedure (synthetic markets only).

Added after the fifth simulated review. `reference_allocation.py` compares its own floating-point Algorithm 1 with an
exact rational-arithmetic textbook procedure; this script does the same for the platform function that produced every
reported number, on the same 480 synthetic markets (no personal data).

  python3 platform_exact.py dump       writes out/platform-exact-markets.json (the markets of textbook_comparison)
  node platform_exact.mjs              runs the platform function on them (needs the platform repository) and writes
                                       out/platform-exact-platform.json
  python3 platform_exact.py compare    writes data/platform-exact.json: the largest differences from the exact
                                       procedure in held mass, Fractional and v3 cutoffs, and rejected-score sets;
                                       without out/platform-exact-platform.json it reads the stored copy in data/
"""
import json
import math
import random
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import PAPER, output_path  # noqa: E402
from reference_allocation import cutoffs, large_market, market, textbook_da  # noqa: E402

SEED = 20261126


def markets():
    """The markets of reference_allocation.textbook_comparison, in the same order and with the same seeds."""
    out = []
    for label, generator, count in (('40x6', market, 200), ('400x40', large_market, 40)):
        for offset, weights in enumerate(('uniform', 'loguniform')):
            rng = random.Random(SEED + 1000 * offset + (0 if label == '40x6' else 500))
            for k in range(count):
                candidates, capacity = generator(rng, weights)
                out.append({'label': f'{label} {weights}', 'index': k,
                            'capacity': {str(d): q for d, q in capacity.items()},
                            'candidates': [{'id': c, 'weight': w, 'prefs': [[d, s] for d, s in prefs]}
                                           for c, (w, prefs) in candidates.items()]})
    return out


def dump():
    path = output_path('platform-exact-markets.json')
    path.write_text(json.dumps({'seed': SEED, 'markets': markets()}))
    print(path)


def compare():
    source = output_path('platform-exact-platform.json')
    if not source.exists():
        source = PAPER / 'data/platform-exact-platform.json'  # the stored platform output, for readers without the repository
    platform = json.loads(source.read_text())
    worst = {}
    mismatched_rejected = 0
    for spec, result in zip(markets(), platform['markets']):
        assert spec['label'] == result['label'] and spec['index'] == result['index']
        candidates = {c['id']: (c['weight'], [tuple(p) for p in c['prefs']]) for c in spec['candidates']}
        capacity = {int(d): q for d, q in spec['capacity'].items()}
        exact_candidates = {c: (Fraction(w), prefs) for c, (w, prefs) in candidates.items()}
        exact, exact_rejected, _ = textbook_da(exact_candidates, capacity)
        held = {int(d): {int(c): m for c, m in h.items()} for d, h in result['held'].items()}
        rejected = {int(d): v for d, v in result['rejected'].items()}
        for d in capacity:
            held.setdefault(d, {})
            rejected.setdefault(d, [])
        w = worst.setdefault(spec['label'], {'markets': 0, 'mass': 0.0, 'fractional_cutoff': 0.0, 'v3_cutoff': 0.0,
                                             'max_events': 0})
        w['markets'] += 1
        w['max_events'] = max(w['max_events'], result['events'])
        for d in capacity:
            for c in set(held[d]) | set(exact[d]):
                w['mass'] = max(w['mass'], abs(held[d].get(c, 0.0) - float(exact[d].get(c, 0))))
            if set(rejected[d]) != set(exact_rejected[d]):
                mismatched_rejected += 1
        a = cutoffs(candidates, held, rejected)
        b = cutoffs(candidates, {d: {c: float(m) for c, m in h.items()} for d, h in exact.items()}, exact_rejected)
        for d in set(a) | set(b):
            if d not in a or d not in b:
                w['fractional_cutoff'] = math.inf
                continue
            w['fractional_cutoff'] = max(w['fractional_cutoff'], abs(a[d][0] - b[d][0]))
            w['v3_cutoff'] = max(w['v3_cutoff'], abs(a[d][1] - b[d][1]))
    out = {'note': 'exploratory, added after the fifth simulated review; synthetic markets only',
           'platform_function': platform['function'], 'platform_commit': platform.get('platformHead'),
           'seed': SEED, 'departments_with_different_rejected_score_sets': mismatched_rejected, 'largest_differences': worst}
    (PAPER / 'data/platform-exact.json').write_text(json.dumps(out, indent=2) + '\n')
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    {'dump': dump, 'compare': compare}[sys.argv[1]]()
