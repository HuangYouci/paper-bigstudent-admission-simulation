"""Checks of the released files' disclosure rule (Supplement S3)."""
import csv
import json
import unittest

from analyze import PAPER, common_rows, load_rows, metrics, tier

SIMULATED = ('v1', 'v2', 'fractional', 'v3', 'archived_v3')


def read(name):
    with (PAPER / 'data' / name).open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


@unittest.skipUnless(tier() == 'controlled', 'needs the controlled-tier department files')
class DisclosureTests(unittest.TestCase):
    def test_small_departments_withheld(self):
        for row in read('department-benchmark.csv'):
            if int(row['applicant_count']) < 5:
                self.assertTrue(all(row[key] == '' for key in SIMULATED + ('quota_status',)), row['gid'])
        small = {row['gid'] for row in read('department-benchmark.csv') if int(row['applicant_count']) < 5}
        for row in read('weighting-granularity-departments.csv'):
            if row['gid'] in small:
                self.assertTrue(all(value == '' for key, value in row.items() if key != 'gid'))

    def test_released_values_have_two_decimals(self):
        for name, keys in (('department-benchmark.csv', SIMULATED), ('weighting-granularity-departments.csv', None)):
            for row in read(name):
                for key, value in row.items():
                    if (keys is None and key != 'gid' or keys and key in keys) and value != '':
                        self.assertLessEqual(len(value.split('.')[-1]) if '.' in value else 0, 2, (name, key, value))

    def test_no_run_values_or_full_hashes_released(self):
        self.assertFalse((PAPER / 'data/archived-run-cutoffs.csv').exists())
        for path in (PAPER / 'data').glob('*.json'):
            self.assertNotIn('FullSHA256', path.read_text(encoding='utf-8'), path.name)

    def test_stored_statistics_match_released_file(self):
        stored = json.loads((PAPER / 'data/analysis-results.json').read_text())
        rows = load_rows()
        j2 = common_rows(rows, ('v3', 'baseline'))
        j5 = common_rows(rows, ('v1', 'v2', 'fractional', 'v3', 'baseline'))
        self.assertEqual(stored['pairs_n'], len(j2))
        self.assertEqual(stored['common_n'], len(j5))
        self.assertAlmostEqual(stored['pairs_v3']['mae'], metrics(j2, 'v3')['mae'], places=12)
        self.assertAlmostEqual(stored['ablation']['v3']['mae'], metrics(j5, 'v3')['mae'], places=12)


@unittest.skipUnless(tier() == 'public', 'checks the public tier')
class PublicTierTests(unittest.TestCase):
    def test_public_rule(self):
        rows = read('department-benchmark.csv')
        self.assertTrue(all(r['v1'] == r['v2'] == r['fractional'] == '' for r in rows))
        released = [r for r in rows if r['v3'] != '']
        self.assertTrue(all(r['confidence'] == 'normal' for r in released))
        self.assertTrue(all(r['archived_v3'] == '' and r['quota_status'] == '' for r in rows if r['v3'] == ''))
        self.assertFalse((PAPER / 'data' / 'weighting-granularity-departments.csv').exists())

    def test_engine_columns_follow_v3(self):
        v3 = {r['gid']: r['v3'] for r in read('department-benchmark.csv')}
        for e in read('engine-2026.csv'):
            if v3.get(e['gid'], '') == '':
                self.assertEqual(e['august_rule'], '')
                self.assertEqual(e['august_rule_engine'], '')


if __name__ == '__main__':
    unittest.main()
