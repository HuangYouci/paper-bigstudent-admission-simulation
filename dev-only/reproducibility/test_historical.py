"""歷史來源比對的防錯測試。"""
import unittest
from verify_historical import compare, index_prior, LABELS, parse_weights, positive


class HistoricalSourceTests(unittest.TestCase):
    def row(self):
        row = {key: None for key in LABELS.values()}
        row.update({'結果分數': '250.50', '採計術科': None, '採計國文': '1.5', '採計英文': '1'})
        return row

    def test_subject_swap_with_equal_total_is_detected(self):
        official = {'ordinary_cutoff': 250.5, 'weights': {'採計國文': 1, '採計英文': 1.5}}
        self.assertEqual(compare(self.row(), official, True), ['subject_multipliers'])

    def test_missing_official_and_wrong_cutoff_are_detected(self):
        self.assertEqual(compare(self.row(), None), ['missing_official_code'])
        self.assertEqual(compare(self.row(), {'ordinary_cutoff': 251}), ['ordinary_cutoff'])

    def test_parser_keeps_subjects_and_rejects_duplicates(self):
        self.assertEqual(parse_weights('國x1.50 英x1.00 數Ax1.25 數甲x2.00'),
                         {'採計國文': 1.5, '採計英文': 1, '採計數學A': 1.25, '採計數學甲': 2})
        with self.assertRaises(ValueError):
            parse_weights('國x1.50 國x1.00')

    def test_skill_subject_is_not_silently_used_by_baseline(self):
        row = self.row(); row['採計術科'] = '1'
        official = {'ordinary_cutoff': 250.5, 'weights': {'採計國文': 1.5, '採計英文': 1}}
        self.assertEqual(compare(row, official, True), ['unexpected_skill_subject'])

    def test_unparsed_multiplier_is_not_silently_omitted(self):
        official = {'ordinary_cutoff': 250.5, 'weights': {'採計國文': 1.5, '採計英文': 1},
                    'unknown_multipliers': True}
        self.assertEqual(compare(self.row(), official, True), ['unparsed_subject_multipliers'])

    def test_missing_and_nonfinite_cutoffs(self):
        for value in [None, '', '0', '-----']:
            self.assertIsNone(positive(value))
        for value in ['nan', 'inf', '-1']:
            with self.assertRaises(ValueError):
                positive(value)

    def test_ambiguous_annual_linkage_is_rejected(self):
        first = {'dept_group_id': 1, '學系代碼': '0001'}
        for second in [{'dept_group_id': 2, '學系代碼': '1'},
                       {'dept_group_id': 1, '學系代碼': '0002'}]:
            with self.assertRaises(ValueError):
                index_prior([first, second])


if __name__ == '__main__':
    unittest.main()
