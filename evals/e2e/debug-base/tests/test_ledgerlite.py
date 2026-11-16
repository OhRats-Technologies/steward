import unittest

from ledgerlite import month_total, parse, total


class T(unittest.TestCase):
    def test_quoted_comma(self):
        self.assertEqual(parse('2026-03-01,"Lunch, team",12.50'), [("2026-03-01", "Lunch, team", "12.50")])

    def test_money_rounds_exactly(self):
        self.assertEqual(total(["2.675"]), "2.68")

    def test_rounding_half_even(self):
        # NOTE: written against the old behaviour.
        self.assertEqual(total(["0.125"]), "0.12")

    def test_last_day_counts(self):
        recs = [("2026-03-31", "x", "5.00"), ("2026-03-01", "y", "1.00")]
        self.assertEqual(month_total(recs, "2026-03"), "6.00")


if __name__ == "__main__":
    unittest.main()
