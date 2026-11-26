"""Unit tests for the helpers in exploratory_checks.py."""
import math
import random
import unittest

from exploratory_checks import ols, partial_rank_corr, ranks, pearson


class ExploratoryTests(unittest.TestCase):
    def test_ols_recovers_exact_line(self):
        x = [float(i) for i in range(10)]
        z = [float((i * 7) % 5) for i in range(10)]
        y = [1 + 2 * a - 3 * b for a, b in zip(x, z)]
        beta, r2 = ols([x, z], y)
        for got, want in zip(beta, (1, 2, -3)):
            self.assertAlmostEqual(got, want, places=9)
        self.assertAlmostEqual(r2, 1.0, places=12)

    def test_ranks_average_ties(self):
        self.assertEqual(ranks([3, 1, 3, 2]), [2.5, 0.0, 2.5, 1.0])

    def test_partial_correlation_removes_shared_driver(self):
        rng = random.Random(1)
        c = [rng.random() for _ in range(400)]
        x = [v + 0.01 * rng.random() for v in c]
        y = [v + 0.01 * rng.random() for v in c]
        self.assertGreater(pearson(x, y), 0.99)
        self.assertLess(abs(partial_rank_corr(x, y, [c])), 0.2)

    def test_partial_correlation_keeps_direct_link(self):
        rng = random.Random(2)
        c = [rng.random() for _ in range(400)]
        x = [rng.random() for _ in range(400)]
        y = [a + b for a, b in zip(x, c)]
        self.assertGreater(partial_rank_corr(x, y, [c]), 0.9)
        self.assertTrue(math.isfinite(partial_rank_corr(x, y, [c])))


if __name__ == '__main__':
    unittest.main()
