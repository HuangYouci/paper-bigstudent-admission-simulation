"""官方表頭解析的格式、重複與整數人數驗證。"""
import unittest
from verify_marginals import parse_rows


def header():
    row = [None] * 14
    row[0], row[1], row[7] = '級分', '國文', '英文'
    return row


def level(count=7):
    row = [None] * 14
    row[0], row[1], row[7] = '60', count, 0
    return row


class MarginalParsingTests(unittest.TestCase):
    def test_header_and_real_zero(self):
        values = parse_rows([header(), level()])
        self.assertEqual(values[('ast_gsat_chinese', 60)], 7)
        self.assertEqual(values[('ast_gsat_english', 60)], 0)

    def test_duplicate_level_rejected(self):
        with self.assertRaises(ValueError):
            parse_rows([header(), level(), level()])

    def test_missing_or_fractional_count_rejected(self):
        for count in (None, -1, 0.5, '7', True, float('nan'), float('inf')):
            with self.subTest(count=count), self.assertRaises(ValueError):
                parse_rows([header(), level(count)])


if __name__ == '__main__':
    unittest.main()
