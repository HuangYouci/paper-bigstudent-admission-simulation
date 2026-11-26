import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from history_checks import detection  # noqa: E402
from practice_baseline import position, total_at  # noqa: E402


class HistoryCheckTests(unittest.TestCase):
    def test_detection_table_precision_and_recall(self):
        d = [2.0, 1.5, -2.0, -1.2, 0.3, -0.4]
        s = [1.5, -1.5, -2.5, 0.2, 1.1, -1.3]
        out = detection(d, s, 1.0)
        table = out['table_flag_by_event']
        self.assertEqual(table['hot'], {'hot': 1, 'neutral': 1, 'cold': 0})
        self.assertEqual(table['cold'], {'hot': 1, 'neutral': 1, 'cold': 1})
        self.assertAlmostEqual(out['hot']['precision'], 0.5)
        self.assertAlmostEqual(out['hot']['recall'], 0.5)
        self.assertAlmostEqual(out['cold']['precision'], 1 / 3)
        self.assertAlmostEqual(out['cold']['recall'], 0.5)
        self.assertEqual(out['flagged'], 5)
        self.assertAlmostEqual(out['direction_agreement'], 4 / 5)

    def test_exact_conversion_inverts_itself(self):
        table = [{'level': k, 'people': p, 'cum_below': sum([5, 10, 20, 10, 5][:k + 1]),
                  'cum_above': sum([5, 10, 20, 10, 5][k:])} for k, p in enumerate([5, 10, 20, 10, 5])]
        for by in ('pr', 'count'):
            for total in (0.5, 1.0, 2.3, 3.7):
                self.assertAlmostEqual(total_at(table, position(table, total, by), by), total)


if __name__ == '__main__':
    unittest.main()
