"""官方學測人數格式、欄位完整性與累計一致性測試。"""
import unittest
from verify_baseline_inputs import count, parse_gsat


def fixture():
    """各級分一人，提供完整的三組雙科表。"""
    rows = []
    for first, second in [('國文', '英文'), ('數學A', '數學B'), ('社會', '自然')]:
        header = [None] * 14
        header[0], header[1], header[7] = '級分', first, second
        rows.append(header)
        for level in range(16):
            row = [None] * 14
            row[0] = str(level)
            for col in (1, 7):
                row[col], row[col + 2] = 1, level + 1
            rows.append(row)
    return rows


class BaselineInputTests(unittest.TestCase):
    def test_complete_official_layout(self):
        self.assertEqual(len(parse_gsat(fixture())), 96)

    def test_invalid_people_are_rejected(self):
        for value in [True, -1, 1.5, float('nan'), float('inf'), '1']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                count(value)

    def test_missing_grade_is_rejected(self):
        rows = fixture()
        del rows[5]
        with self.assertRaises(ValueError):
            parse_gsat(rows)

    def test_inconsistent_cumulative_is_rejected(self):
        rows = fixture()
        rows[1][3] = 2
        with self.assertRaises(ValueError):
            parse_gsat(rows)
