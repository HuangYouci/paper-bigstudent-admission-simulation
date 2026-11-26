"""檢驗基準尺度、缺值、PR 端點及中點定義。"""
import unittest
from reproduce_baseline import curve, score_at_pr, weighted_score, weighted_pr, prediction


class BaselineTests(unittest.TestCase):
    def test_midpoint_percentile(self):
        self.assertEqual(curve([dict(level=0, people=2, cum_below=2), dict(level=1, people=6, cum_below=8)]), [(0, 12.5), (1, 62.5)])

    def test_interpolation_and_clamping(self):
        points = [(0, 20), (15, 80)]
        self.assertEqual([score_at_pr(points, x) for x in (0, 50, 100)], [0, 7.5, 15])

    def test_gsat15_is_scaled_but_ast60_is_not(self):
        d = {'2026:gsat_chinese': [(0, 0), (15, 100)], '2026:ast_mathA': [(0, 0), (60, 100)]}
        items = [dict(subject='gsat_chinese', kind='gsat60', weight=2), dict(subject='ast_mathA', kind='ast', weight=1)]
        self.assertEqual(weighted_score(items, 2026, 50, d), 90)
        self.assertAlmostEqual(weighted_pr(items, 2026, 90, d), 50)

    def test_missing_distribution_does_not_fallback(self):
        self.assertIsNone(weighted_score([dict(subject='gsat_chinese', kind='gsat60', weight=1)], 2026, 50, {'2025:gsat_chinese': [(0, 0), (15, 100)]}))

    def test_absent_or_skill_history_returns_missing(self):
        self.assertIsNone(prediction(dict(prior=None), {}))
        self.assertIsNone(prediction(dict(prior=dict(cutoff=10, hasSkill=True, items=[])), {}))

    def test_insufficient_or_empty_distribution_is_unavailable(self):
        self.assertIsNone(curve([]))
        self.assertIsNone(curve([dict(level=0, people=0, cum_below=0), dict(level=1, people=0, cum_below=0)]))
