"""Tests of the fifth-revision checks (revision_checks.py)."""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import revision_checks as rc  # noqa: E402
from analyze import load_rows, tier  # noqa: E402


class RevisionChecks(unittest.TestCase):
    @unittest.skipUnless(tier() == 'controlled', 'needs the controlled-tier department file')
    def test_every_institution_has_a_region(self):
        for row in load_rows():
            self.assertIn(rc.region_of(row), rc.REGION)

    def test_ecdf_matches_brute_force(self):
        rng = random.Random(1)
        values = [rng.gauss(0, 2) for _ in range(300)]
        f = rc.Ecdf(values)
        for u in (-5, -0.3, 0, 1.7, 9):
            self.assertAlmostEqual(f.mean_abs(u), sum(abs(v - u) for v in values) / len(values), places=9)
        gini = sum(abs(a - b) for a in values for b in values) / len(values) ** 2
        self.assertAlmostEqual(f.gini, gini, places=9)

    def test_pinball_at_the_median_is_half_the_absolute_error(self):
        for u in (-2.5, 0.0, 1.25):
            self.assertAlmostEqual(rc.pinball(u, 0.5), abs(u) / 2)

    def test_sign_test(self):
        self.assertAlmostEqual(rc.sign_test(5, 10), 1.0)
        self.assertAlmostEqual(rc.sign_test(0, 5), 2 / 32)

    def test_robust_slopes_recover_a_line(self):
        xs = [x / 10 for x in range(-50, 51)]
        ys = [0.3 + 0.5 * x for x in xs]
        ys[0] += 40  # one gross outlier
        self.assertAlmostEqual(rc.lad(xs, ys), 0.5, places=3)
        self.assertAlmostEqual(rc.huber(xs, ys), 0.5, places=2)


if __name__ == '__main__':
    unittest.main()
