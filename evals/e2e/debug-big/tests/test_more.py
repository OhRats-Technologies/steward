import json
import unittest

from ledgerlite import by_category, convert, month_total, norm_date, to_json
from ledgerlite.util import norm


class More(unittest.TestCase):
    def test_norm_strips(self):
        self.assertEqual(norm("  Food "), "food")

    def test_unpadded_date(self):
        self.assertEqual(norm_date("2026-3-1"), "2026-03-01")

    def test_month_total_unpadded(self):
        self.assertEqual(month_total([("2026-3-9", "x", "2.00")], "2026-03"), "2.00")

    def test_convert_multiplies(self):
        self.assertEqual(convert("10.00", "EUR", {"EUR": 0.9}), "9.00")

    def test_category_case_and_space(self):
        recs = [("2026-03-01", "a", "1.00", " Food"), ("2026-03-02", "b", "2.00", "rent")]
        self.assertEqual([r[1] for r in by_category(recs, "FOOD")], ["a"])

    def test_json_amounts_are_strings(self):
        self.assertEqual(json.loads(to_json([("2026-03-01", "a", "0.10")]))[0]["amount"], "0.10")


if __name__ == "__main__":
    unittest.main()
