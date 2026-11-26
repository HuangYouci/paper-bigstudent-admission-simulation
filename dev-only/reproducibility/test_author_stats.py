"""author_stats.py, given the released v3 values in place of a rerun, must reproduce the released statistics."""
import json
import unittest

from analyze import PAPER, tier
from author_stats import j2_rows, label_stats, level_stats


@unittest.skipUnless(tier() == 'controlled', 'needs the controlled-tier department file')
class AuthorStatsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.j2 = j2_rows()
        cls.released = {r['gid']: r['v3'] for r in cls.j2}
        cls.stats = label_stats(cls.j2, cls.released, intervals=False)

    def test_released_values_reproduce_table_5(self):
        decision = json.loads((PAPER / 'data/decision-checks.json').read_text())['decision']['all']
        self.assertEqual(self.stats['covered'], 1521)
        self.assertAlmostEqual(self.stats['combination']['mae'], decision['combination']['mae'], places=9)
        self.assertAlmostEqual(self.stats['baseline']['mae'], decision['historical']['mae'], places=9)
        self.assertAlmostEqual(self.stats['prediction']['mae'], decision['v3']['mae'], places=9)

    def test_released_values_reproduce_table_6(self):
        flags = json.loads((PAPER / 'data/decision-checks.json').read_text())['flags']['raw']['1.0']
        self.assertEqual(self.stats['flags_delta1']['flagged'], flags['flagged'])
        self.assertAlmostEqual(self.stats['flags_delta1']['direction_agreement'], flags['direction_agreement'], places=12)

    def test_missing_values_fall_back_to_the_baseline(self):
        partial = dict(self.released)
        dropped = [r['gid'] for r in self.j2[:100]]
        for gid in dropped:
            partial[gid] = None
        stats = label_stats(self.j2, partial, intervals=False)
        self.assertEqual(stats['covered'], 1421)
        self.assertEqual(stats['combination']['n'], 1521)

    def test_level_stats_partition_the_covered_departments(self):
        levels = level_stats(self.j2, self.released)
        self.assertEqual(sum(v['n'] for v in levels.values()), 1521)


if __name__ == '__main__':
    unittest.main()
