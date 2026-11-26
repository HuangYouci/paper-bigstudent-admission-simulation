import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference_allocation import audit, cutoffs, divisible_da, market, table3, whole_person  # noqa: E402


class ReferenceAllocationTests(unittest.TestCase):
    def test_table3(self):
        result = table3()
        self.assertEqual(result['v2_cutoff_by_order']['ABC'], 150)
        self.assertEqual(result['v2_cutoff_by_order']['BCA'], 220)
        self.assertEqual(len(result['fractional_outcomes']), 1)
        (holdings, (fractional, v3)), = result['fractional_outcomes']
        self.assertEqual([list(h) for h in holdings], [[1, 9.0], [2, 3.0]])
        self.assertEqual(fractional, 195)
        self.assertAlmostEqual(v3, 545 / 3)

    def test_divisible_mass_is_stable_feasible_and_order_invariant(self):
        rng = random.Random(7)
        for weights in ('unit', 'uniform', 'loguniform'):
            candidates, capacity = market(rng, weights)
            first, _, _ = divisible_da(candidates, capacity)
            self.assertLess(max(audit(candidates, capacity, first).values()), 1e-6)
            shuffled = rng.sample(list(candidates), len(candidates))
            second, _, _ = divisible_da(candidates, capacity, shuffled)
            for dept in capacity:
                for cid in set(first[dept]) | set(second[dept]):
                    self.assertAlmostEqual(first[dept].get(cid, 0.0), second[dept].get(cid, 0.0), places=9)

    def test_unit_weights_match_whole_person(self):
        rng = random.Random(11)
        candidates, capacity = market(rng, 'unit')
        held, rejected, _ = divisible_da(candidates, capacity)
        whole = whole_person(candidates, capacity)
        self.assertEqual({d: sorted(h) for d, h in held.items()}, {d: sorted(h) for d, h in whole.items()})
        for dept, (fractional, v3) in cutoffs(candidates, held, rejected).items():
            self.assertEqual(fractional, v3)


if __name__ == '__main__':
    unittest.main()
