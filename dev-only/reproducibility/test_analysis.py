"""驗證論文數值計算的分母、容差與缺值處理。"""
import unittest
from analyze import common_rows, metrics, clustered_difference, error_share, load_rows, tier


def row(gid=1, school='A', actual=10, scale=2, a=12, b=10, **extra):
    return dict(gid=gid, school=school, actual=actual, weightTotal=scale, a=a, b=b, **extra)


class AnalysisTests(unittest.TestCase):
    def test_missing_value_not_replaced_by_zero(self):
        selected = common_rows([row(), row(gid=2, a=None, b=100)], ('a', 'b'))
        self.assertEqual(len(selected), 1)
        self.assertEqual(metrics(selected, 'a')['mae'], 1)

    def test_zero_is_valid_prediction(self):
        self.assertEqual(len(common_rows([row(a=0)], ('a',))), 1)

    def test_duplicate_and_invalid_scale_rejected(self):
        for values in ([row(), row()], [row(scale=0)], [row(actual=float('inf'))]):
            with self.assertRaises(ValueError):
                common_rows(values, ('a',))

    def test_unequal_clusters_preserve_department_mean(self):
        values = [row(gid=i, school=s, actual=10, scale=1, a=a) for i, (s, a) in enumerate([('A', 11), ('A', 11), ('B', 14)])]
        output = clustered_difference(values, 'a', 'b', 1000)
        self.assertEqual(output, dict(difference=2, lower=1, upper=4, schools=2))
        reverse = clustered_difference(values, 'b', 'a', 1000)
        self.assertEqual(reverse['difference'], -2)

    def test_weighted_metrics_and_invalid_weights(self):
        values = [row(gid=1, a=12, q=1), row(gid=2, a=18, q=3)]
        self.assertEqual(metrics(values, 'a', 'q')['mae'], 3.25)
        with self.assertRaises(ValueError):
            metrics([row(q=-1)], 'a', 'q')

    def test_raw_and_standardized_tolerances_differ(self):
        values = [row(a=18, scale=4)]
        self.assertEqual(error_share(values, 'a', 5), 0)
        self.assertEqual(error_share(values, 'a', 5, True), 1)

    @unittest.skipUnless(tier() == 'controlled', 'needs the controlled-tier department file')
    def test_frozen_availability_denominator(self):
        values = load_rows()
        missing = [value for value in values if value['no_history_in_snapshot']]
        supported = common_rows(missing, ('v3',))
        # Simulated values of departments with fewer than five listings are withheld (README), and
        # every published statistic is computed from these released values.
        self.assertEqual(sum(1 for value in values if value['applicant_count'] < 5), 52)
        self.assertTrue(all(value['v3'] is None for value in values if value['applicant_count'] < 5))
        self.assertEqual((len(values), len(missing), len(supported)), (1706, 110, 74))
        self.assertEqual(len(common_rows(values, ('v3', 'baseline'))), 1521)
        self.assertEqual(len(common_rows(values, ('v1', 'v2', 'fractional', 'v3', 'baseline'))), 1361)

if __name__ == '__main__':
    unittest.main()
