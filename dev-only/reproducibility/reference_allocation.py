"""Independent reference implementation of the allocation rules in Section 4 (standard library only).

Readers cannot run the platform's allocation code, so this file re-implements, from the
descriptions in the manuscript, the whole-person rule of v2 (Section 4.3, Table 2), divisible-mass
deferred acceptance (Algorithm 1), the reported cutoffs of Fractional and v3 (Section 4.5), and an
audit of feasibility and stability that scans every eligible edge. It reproduces the example of Section 4.3 and runs
synthetic markets drawn with the specification of Supplement S17, using Python's own random number
generator, so its counts are an independent check of the pattern rather than a replay of S17.

Usage: python3 reference_allocation.py   (writes out/reference-allocation.json; about 10 s)
"""
import itertools
import json
import math
import random
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import output_path  # noqa: E402

EPS = 1e-7


def priority_key(score, cid):
    """Higher score first; ties broken by candidate identifier (lower first)."""
    return (-score, cid)


def divisible_da(candidates, capacity, order=None, lifo=False, max_events=None):
    """Algorithm 1. candidates: {cid: (weight, [(dept, score), ...] in preference order)}.

    Displaced mass is queued in pieces, first in, first out (last in, first out if lifo=True).
    Returns held mass {dept: {cid: mass}}, rejected scores {dept: [score, ...]}, and the event count;
    the event count is None when max_events is reached.
    """
    held = {d: {} for d in capacity}
    rejected = {d: [] for d in capacity}
    score_at = {c: dict(prefs) for c, (_, prefs) in candidates.items()}
    queue = [(c, 0, candidates[c][0]) for c in (order or list(candidates)) if candidates[c][1]]
    events = 0
    while queue:
        cid, index, mass = queue.pop() if lifo else queue.pop(0)
        events += 1
        if max_events and events > max_events:
            return held, rejected, None
        prefs = candidates[cid][1]
        if mass <= EPS or index >= len(prefs):
            continue
        dept = prefs[index][0]
        if capacity[dept] <= 0:
            queue.append((cid, index + 1, mass))
            continue
        held[dept][cid] = held[dept].get(cid, 0.0) + mass
        room = capacity[dept]
        keep = {}
        for holder in sorted(held[dept], key=lambda h: priority_key(score_at[h][dept], h)):
            amount = held[dept][holder]
            retained = min(amount, max(room, 0.0)) if room > EPS else 0.0
            room -= retained
            displaced = amount - retained
            if displaced > EPS:
                rejected[dept].append(score_at[holder][dept])
                queue.append((holder, prefs_index(candidates[holder][1], dept) + 1, displaced))
            if retained > EPS:
                keep[holder] = retained
        held[dept] = keep
    return held, rejected, events


def prefs_index(prefs, dept):
    return [d for d, _ in prefs].index(dept)


def textbook_da(candidates, capacity):
    """Textbook proposal procedure for stable allocation in exact rational arithmetic: a candidate
    proposes all of its unassigned mass to the best department that has not rejected it; a
    department keeps the highest-priority mass up to capacity and returns the rest to its owners.
    Returns held mass, rejected scores, and the number of proposals."""
    score_at = {c: dict(prefs) for c, (_, prefs) in candidates.items()}
    order = {c: [d for d, _ in prefs] for c, (_, prefs) in candidates.items()}
    unassigned = {c: Fraction(w) for c, (w, _) in candidates.items()}
    pointer = {c: 0 for c in candidates}
    cap = {d: Fraction(q) for d, q in capacity.items()}
    held = {d: {} for d in capacity}
    rejected = {d: [] for d in capacity}
    active = [c for c in candidates if order[c]]
    proposals = 0
    while active:
        c = active.pop(0)
        if unassigned[c] == 0 or pointer[c] >= len(order[c]):
            continue
        d = order[c][pointer[c]]
        proposals += 1
        if cap[d] <= 0:
            pointer[c] += 1
            active.append(c)
            continue
        held[d][c] = held[d].get(c, Fraction(0)) + unassigned[c]
        unassigned[c] = Fraction(0)
        room, keep = cap[d], {}
        for h in sorted(held[d], key=lambda h: priority_key(score_at[h][d], h)):
            kept = min(held[d][h], max(room, Fraction(0)))
            room -= kept
            if held[d][h] > kept:
                unassigned[h] += held[d][h] - kept
                rejected[d].append(score_at[h][d])
                if pointer[h] < len(order[h]) and order[h][pointer[h]] == d:
                    pointer[h] += 1
                if h not in active:
                    active.append(h)
            if kept > 0:
                keep[h] = kept
        held[d] = keep
    return held, rejected, proposals


def whole_person(candidates, capacity, order=None):
    """v2: holders and the proposer are sorted by priority and accumulate full weights; at the
    first candidate whose remaining capacity is below half its weight, that candidate and everyone
    behind are rejected; a rejected candidate moves to its next preference and never returns."""
    held = {d: [] for d in capacity}
    score_at = {c: dict(prefs) for c, (_, prefs) in candidates.items()}
    queue = [(c, 0) for c in (order or list(candidates)) if candidates[c][1]]
    while queue:
        cid, index = queue.pop(0)
        prefs = candidates[cid][1]
        if index >= len(prefs):
            continue
        dept = prefs[index][0]
        if capacity[dept] <= 0:
            queue.append((cid, index + 1))
            continue
        members = sorted(held[dept] + [cid], key=lambda h: priority_key(score_at[h][dept], h))
        room, keep, stop = capacity[dept], [], False
        for holder in members:
            weight = candidates[holder][0]
            if not stop and room >= weight / 2:
                keep.append(holder)
                room -= weight
            else:
                stop = True
                queue.append((holder, prefs_index(candidates[holder][1], dept) + 1))
        held[dept] = keep
    return {d: {c: candidates[c][0] for c in members} for d, members in held.items()}


def cutoffs(candidates, held, rejected):
    """Fractional: lowest score with retained mass. v3: alpha interpolation of Section 4.5."""
    out = {}
    for dept, holders in held.items():
        if not holders:
            continue
        scores = {h: dict(candidates[h][1])[dept] for h in holders}
        marginal = min(holders, key=lambda h: (scores[h], -h if isinstance(h, int) else 0))
        s_m = scores[marginal]
        lower = [s for s in rejected[dept] if s < s_m]
        fractional = s_m
        v3 = s_m
        if lower:
            w = candidates[marginal][0]
            f = min(1.0, max(0.0, holders[marginal] / w))
            alpha = f * max(0.0, 1 - 1 / w)
            v3 = s_m - alpha * (s_m - max(lower))
        out[dept] = (fractional, v3)
    return out


def audit(candidates, capacity, held, tol=1e-6):
    """Largest capacity excess, largest overallocation of a candidate, and largest blocking mass."""
    alloc = {c: {} for c in candidates}
    for d, holders in held.items():
        for c, m in holders.items():
            alloc[c][d] = m
    excess = max([sum(h.values()) - capacity[d] for d, h in held.items()] + [0.0])
    over = max([sum(a.values()) - candidates[c][0] for c, a in alloc.items()] + [0.0])
    blocking = 0.0
    for c, (w, prefs) in candidates.items():
        better = 0.0
        for d, s in prefs:
            better += alloc[c].get(d, 0.0)          # mass held at d or a better department
            if capacity[d] <= 0 or alloc[c].get(d, 0.0) >= w - tol:
                continue
            higher = sum(m for h, m in held[d].items()
                         if priority_key(dict(candidates[h][1])[d], h) <= priority_key(s, c))
            blocking = max(blocking, min(w - better, capacity[d] - higher))
    return {'capacity_excess': excess, 'candidate_excess': over, 'blocking_mass': max(blocking, 0.0)}


def table3():
    candidates = {1: (9, [('j', 220)]), 2: (9, [('j', 195)]), 3: (1, [('j', 150)])}
    capacity = {'j': 12}
    names = {1: 'A', 2: 'B', 3: 'C'}
    v2_cutoffs, fractional = {}, set()
    for order in itertools.permutations([1, 2, 3]):
        v2 = whole_person(candidates, capacity, list(order))
        v2_cutoffs[''.join(names[c] for c in order)] = min(dict(candidates[c][1])['j'] for c in v2['j'])
        held, rejected, _ = divisible_da(candidates, capacity, list(order))
        fractional.add((tuple(sorted(held['j'].items())), cutoffs(candidates, held, rejected)['j']))
    return {'v2_cutoff_by_order': v2_cutoffs, 'fractional_outcomes': [list(x) for x in fractional]}


def market(rng, weights):
    capacity = {d: rng.randint(0, 20) for d in range(6)}
    candidates = {}
    for c in range(40):
        depts = rng.sample(range(6), rng.randint(1, 6))
        w = 1.0 if weights == 'unit' else (rng.uniform(1, 4) if weights == 'uniform' else math.exp(rng.uniform(0, math.log(100))))
        candidates[c] = (w, [(d, rng.randint(0, 60)) for d in depts])
    return candidates, capacity


def synthetic(markets=200, seed=20261008):
    out = {}
    for offset, weights in enumerate(('unit', 'uniform', 'loguniform')):
        rng = random.Random(seed + 10_000 * offset)
        counts = {'v2_blocking': 0, 'v2_excess': 0, 'v2_order': 0, 'fractional_violations': 0, 'fractional_order': 0,
                  'max_events': 0, 'max_blocking_fractional': 0.0}
        for _ in range(markets):
            candidates, capacity = market(rng, weights)
            orders = [list(candidates)] + [rng.sample(list(candidates), len(candidates)) for _ in range(3)]
            v2_results, f_results = [], []
            v2_block = v2_excess = False
            for order in orders:
                v2 = whole_person(candidates, capacity, order)
                a = audit(candidates, capacity, v2)
                v2_block |= a['blocking_mass'] > 1e-6
                v2_excess |= a['capacity_excess'] > 1e-6
                v2_results.append({d: sorted(h) for d, h in v2.items()})
                held, _, events = divisible_da(candidates, capacity, order)
                b = audit(candidates, capacity, held)
                counts['max_events'] = max(counts['max_events'], events)
                counts['max_blocking_fractional'] = max(counts['max_blocking_fractional'], b['blocking_mass'])
                if max(b.values()) > 1e-6:
                    counts['fractional_violations'] += 1
                f_results.append({d: {c: round(m, 9) for c, m in h.items()} for d, h in held.items()})
            counts['v2_blocking'] += v2_block
            counts['v2_excess'] += v2_excess
            counts['v2_order'] += any(r != v2_results[0] for r in v2_results[1:])
            counts['fractional_order'] += any(r != f_results[0] for r in f_results[1:])
        out[weights] = counts
    return out


def integer_replication(markets=200, seed=20261125):
    """With integer weights, divisible mass should equal unit-weight deferred acceptance on records
    replicated w_i times (replicas adjacent in every priority order). Counts mismatching markets."""
    rng = random.Random(seed)
    mismatches, largest = 0, 0.0
    for _ in range(markets):
        candidates, capacity = market(rng, 'unit')
        candidates = {c: (float(rng.randint(1, 4)), prefs) for c, (_, prefs) in candidates.items()}
        held, _, _ = divisible_da(candidates, capacity)
        # Replicas: candidate c with weight w becomes ids c*10+k, k < w; ties break by id, keeping replicas adjacent.
        replicas = {c * 10 + k: (1.0, prefs) for c, (w, prefs) in candidates.items() for k in range(int(w))}
        unit, _, _ = divisible_da(replicas, capacity)
        market_largest = 0.0
        for d in capacity:
            totals = {}
            for r, m in unit[d].items():
                totals[r // 10] = totals.get(r // 10, 0.0) + m
            for c in set(totals) | set(held[d]):
                market_largest = max(market_largest, abs(totals.get(c, 0.0) - held[d].get(c, 0.0)))
        largest = max(largest, market_largest)
        mismatches += market_largest > 1e-9
    return {'markets': markets, 'weights': 'integers 1-4', 'markets_with_difference': mismatches,
            'largest_difference': largest}


def large_market(rng, weights, candidates=400, departments=40):
    """Larger markets; a random fraction added to each integer score breaks ties separately at each
    department, as the platform's hash does."""
    capacity = {d: rng.randint(0, 30) for d in range(departments)}
    out = {}
    for c in range(candidates):
        depts = rng.sample(range(departments), rng.randint(1, 8))
        w = rng.uniform(1, 4) if weights == 'uniform' else math.exp(rng.uniform(0, math.log(100)))
        out[c] = (w, [(d, rng.randint(0, 60) + rng.random() / 1000) for d in depts])
    return out, capacity


def textbook_comparison(seed=20261126):
    """Algorithm 1 (floating point, pieces, first in first out) against the exact textbook procedure:
    largest differences in held mass, Fractional cutoff and v3 cutoff; and event counts when the
    queue is processed last in, first out."""
    out = {}
    for label, generator, markets in (('40x6', market, 200), ('400x40', large_market, 40)):
        for offset, weights in enumerate(('uniform', 'loguniform')):
            rng = random.Random(seed + 1000 * offset + (0 if label == '40x6' else 500))
            worst = {'mass': 0.0, 'fractional_cutoff': 0.0, 'v3_cutoff': 0.0}
            for _ in range(markets):
                candidates, capacity = generator(rng, weights)
                held, rejected, _ = divisible_da(candidates, capacity)
                exact, exact_rejected, _ = textbook_da(candidates, capacity)
                for d in capacity:
                    for c in set(held[d]) | set(exact[d]):
                        worst['mass'] = max(worst['mass'], abs(held[d].get(c, 0.0) - float(exact[d].get(c, 0))))
                a = cutoffs(candidates, held, rejected)
                b = cutoffs(candidates, {d: {c: float(m) for c, m in h.items()} for d, h in exact.items()}, exact_rejected)
                for d in set(a) | set(b):
                    if d not in a or d not in b:
                        worst['fractional_cutoff'] = math.inf
                        continue
                    worst['fractional_cutoff'] = max(worst['fractional_cutoff'], abs(a[d][0] - b[d][0]))
                    worst['v3_cutoff'] = max(worst['v3_cutoff'], abs(a[d][1] - b[d][1]))
            out[f'{label} {weights}'] = dict(worst, markets=markets)
    rng = random.Random(seed + 7)
    fifo, lifo, capped = [], [], 0
    for _ in range(200):
        candidates, capacity = market(rng, 'uniform')
        fifo.append(divisible_da(candidates, capacity)[2])
        events = divisible_da(candidates, capacity, lifo=True, max_events=1_000_000)[2]
        if events is None:
            capped += 1
        else:
            lifo.append(events)
    out['event_counts_40x6_uniform'] = {'markets': 200, 'fifo_max': max(fifo), 'lifo_max_below_cap': max(lifo),
                                        'lifo_markets_over_1e6_events': capped}
    return out


def main():
    result = {'table3': table3(), 'synthetic_markets_per_condition': 200, 'synthetic': synthetic(),
              'integer_replication': integer_replication(), 'textbook_comparison': textbook_comparison()}
    output_path('reference-allocation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
