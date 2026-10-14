"""A3 — measurement semantics."""
import unittest

from src import metrics


def ob(value, decimals=1, exp=0, status="", desc=""):
    return {"value": value, "decimals": decimals, "scalarExponent": exp,
            "statusSymbol": status, "statusDesc": desc, "symbolSymbol": "", "symbolDesc": ""}


class YearOverYear(unittest.TestCase):
    def test_rate_change_is_percentage_points(self):
        obs = {"2025-09-01": ob(5.4), "2026-09-01": ob(6.1)}
        c = metrics.yoy_change(obs, "2026-09-01", "rate")
        self.assertTrue(c["available"])
        self.assertEqual(c["unit"], "pp")
        self.assertAlmostEqual(c["delta"], 0.7)
        self.assertEqual(metrics.format_change(c), "+0.7 pp")

    def test_count_change_is_percent(self):
        obs = {"2025-09-01": ob(400.0, exp=3), "2026-09-01": ob(410.0, exp=3)}
        c = metrics.yoy_change(obs, "2026-09-01", "count")
        self.assertEqual(c["unit"], "%")
        self.assertAlmostEqual(c["delta"], 2.5)
        self.assertEqual(metrics.format_change(c), "+2.5%")

    def test_count_change_normalises_mixed_scalars(self):
        # 400 thousand vs 410,000 units is the same 2.5% change
        obs = {"2025-09-01": ob(400.0, exp=3), "2026-09-01": ob(410000.0, exp=0)}
        self.assertAlmostEqual(metrics.yoy_change(obs, "2026-09-01", "count")["delta"], 2.5)

    def test_quarterly_compares_same_quarter_last_year(self):
        obs = {"2025-04-01": ob(3.0), "2026-01-01": ob(9.9), "2026-04-01": ob(3.5)}
        c = metrics.yoy_change(obs, "2026-04-01", "rate")
        self.assertEqual(c["baseRef"], "2025-04-01")
        self.assertAlmostEqual(c["delta"], 0.5)

    def test_missing_baseline_is_unavailable_not_zero(self):
        c = metrics.yoy_change({"2026-09-01": ob(5.0)}, "2026-09-01", "rate")
        self.assertFalse(c["available"])
        self.assertEqual(metrics.format_change(c), "Unavailable")

    def test_suppressed_baseline_and_current(self):
        obs = {"2025-09-01": ob(None, status="x"), "2026-09-01": ob(5.0)}
        self.assertFalse(metrics.yoy_change(obs, "2026-09-01", "rate")["available"])
        obs = {"2025-09-01": ob(5.0), "2026-09-01": ob(None, status="F")}
        self.assertFalse(metrics.yoy_change(obs, "2026-09-01", "rate")["available"])

    def test_zero_denominator_is_unavailable_not_infinite(self):
        obs = {"2025-04-01": ob(0, decimals=0), "2026-04-01": ob(15, decimals=0)}
        c = metrics.yoy_change(obs, "2026-04-01", "count")
        self.assertFalse(c["available"])
        self.assertIn("zero", c["reason"])

    def test_negative_change_and_flat(self):
        obs = {"2025-09-01": ob(6.0), "2026-09-01": ob(5.5), "2025-08-01": ob(5.0), "2026-08-01": ob(5.0)}
        self.assertEqual(metrics.format_change(metrics.yoy_change(obs, "2026-09-01", "rate")), "−0.5 pp")
        self.assertEqual(metrics.yoy_change(obs, "2026-08-01", "rate")["direction"], "flat")


class ScalarsAndFlags(unittest.TestCase):
    def test_scalar_from_codeset_description(self):
        self.assertEqual(metrics.scalar_exponent(3, "thousands"), 3)
        self.assertEqual(metrics.scalar_exponent(6, "millions"), 6)
        self.assertEqual(metrics.scalar_exponent(0, "units"), 0)
        self.assertEqual(metrics.scalar_exponent(3, None), 3)  # WDS code convention
        self.assertEqual(metrics.to_absolute(437.2, 3), 437200.0)

    def test_thousands_never_shown_as_people_count(self):
        unit = metrics.unit_label("count", "Persons", "thousands", 3)
        self.assertIn("thousand", unit)
        self.assertEqual(metrics.format_value(ob(437.2, exp=3), "count"), "437.2")

    def test_caution_flag(self):
        self.assertTrue(metrics.is_caution(ob(5.0, status="E", desc="use with caution")))
        self.assertTrue(metrics.is_caution(ob(5.0, status="", desc="Use with caution")))
        self.assertFalse(metrics.is_caution(ob(5.0, status="A", desc="excellent")))
        self.assertEqual(metrics.flag_symbols(ob(5.0, status="E", desc="use with caution")), [("E", "use with caution")])

    def test_unavailable_value_formatting(self):
        self.assertEqual(metrics.format_value(ob(None, status="x"), "rate"), "Unavailable")
        self.assertIn("x", metrics.unavailable_reason(ob(None, status="x", desc="suppressed")))

    def test_period_labels_and_windows(self):
        self.assertEqual(metrics.period_label("2026-09-01", "monthly"), "September 2026")
        self.assertEqual(metrics.period_label("2026-04-01", "quarterly", True), "Q2 2026")
        self.assertEqual(metrics.period_window("2026-02-01", "monthly", 3), ["2025-12-01", "2026-01-01", "2026-02-01"])
        self.assertEqual(metrics.period_window("2026-01-01", "quarterly", 2), ["2025-10-01", "2026-01-01"])


if __name__ == "__main__":
    unittest.main()
