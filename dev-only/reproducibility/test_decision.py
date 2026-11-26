"""Tests for decision_checks.py and the released audit files it reads."""
import csv
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decision_checks import gerrity, flag_summary, optimal_weight  # noqa: E402

PAPER = Path(__file__).resolve().parents[2]


class GerrityTest(unittest.TestCase):
    def test_perfect_constant_and_reversed(self):
        self.assertAlmostEqual(gerrity([[30, 0, 0], [0, 40, 0], [0, 0, 30]]), 1.0)
        self.assertAlmostEqual(gerrity([[10, 10, 10], [10, 10, 10], [10, 10, 10]]), 0.0)
        self.assertLess(gerrity([[0, 0, 30], [0, 40, 0], [30, 0, 0]]), 0.0)

    def test_flag_summary_counts(self):
        d = [2.0, -2.0, 0.5, 1.5]
        s = [1.2, -1.1, 1.3, -0.2]
        out = flag_summary(d, s, 1.0)
        self.assertEqual(out['flagged'], 3)
        self.assertAlmostEqual(out['direction_agreement'], 1.0)
        self.assertAlmostEqual(out['moved_by_threshold_in_flagged_direction'], 2 / 3)


class WeightTest(unittest.TestCase):
    def test_optimal_weight_recovers_known_mixture(self):
        # baseline errors e and v3 errors g + e: optimal weight solves sum((e + w g)^2) minimal.
        rows = [{'actual': 0.0, 'weightTotal': 1.0, 'baseline': b, 'v3': v} for b, v in ((1, -1), (2, -2), (-1, 1))]
        self.assertAlmostEqual(optimal_weight(rows), 0.5)


class AuditFileTest(unittest.TestCase):
    def test_official_rules_audit(self):
        summary = json.loads((PAPER / 'data/official-rules-audit.json').read_text())
        self.assertEqual(summary['officialRows'], 1764)
        self.assertEqual(summary['nonSkillRows'], 1717)
        self.assertEqual(summary['subjectMultiplierMismatches'], 0)
        with (PAPER / 'data/official-rules-audit.csv').open() as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1706)
        self.assertTrue(all(r['multipliers_match'] == 'True' for r in rows))

    def test_relinked_history(self):
        with (PAPER / 'data/history-2024.csv').open() as f:
            rows = list(csv.DictReader(f))
        relinked = [r for r in rows if r['relinked_baseline']]
        self.assertEqual(len(relinked), 27)
        with (PAPER / 'data/department-benchmark.csv').open() as f:
            benchmark = {int(r['gid']): r for r in csv.DictReader(f)}
        self.assertTrue(all(benchmark[int(r['gid'])]['baseline'] == '' for r in relinked))


if __name__ == '__main__':
    unittest.main()
