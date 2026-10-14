"""A4 failure handling, A5 repeat/revision behaviour, label resolution, and build smoke checks."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src import build, collect
from tests.fake_wds import FakeWDS

ROOT = Path(__file__).resolve().parent.parent
T0, T1, T2 = "2026-10-10T17:17:00Z", "2026-10-17T17:17:00Z", "2026-10-24T17:17:00Z"
VIC_UR = "3.7.1.1.0.0.0.0.0.0"   # fake coordinate: VIC / unemployment rate / total gender / 15+
VIC_JVR = "3.3.0.0.0.0.0.0.0.0"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "config").mkdir()
        shutil.copy(ROOT / "config" / "series.json", self.tmp / "config" / "series.json")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def doc(self, name):
        return json.loads((self.tmp / "data" / "official" / f"{name}.json").read_text())

    def status(self):
        return json.loads((self.tmp / "data" / "status.json").read_text())

    def count_obs(self, name):
        return sum(len(s["observations"]) for s in self.doc(name)["series"].values())


class Resolution(Base):
    def test_resolves_by_label_and_records_dimensions(self):
        out = collect.run(self.tmp, fetch=FakeWDS(), now=T0)
        self.assertTrue(out["ok"])
        s = self.doc("labour_force")["series"]["vic.employment"]
        self.assertEqual(s["members"]["Geography"], "Vancouver Island and Coast, British Columbia")
        self.assertEqual(s["members"]["Gender"], "Total - Gender")
        self.assertEqual(s["members"]["Age group"], "15 years and over")
        self.assertEqual(s["scalarDesc"], "thousands")
        self.assertEqual(s["uom"], "Persons")
        self.assertEqual(len(s["observations"]), 36)
        self.assertEqual(len(self.doc("vacancies")["series"]["ca.job_vacancy_rate"]["observations"]), 12)
        self.assertEqual(set(self.doc("labour_force")["series"]),
                         {f"{g}.{m}" for g in ("vic", "bc", "ca") for m in ("employment", "employment_rate", "unemployment_rate")})

    def test_response_order_does_not_matter(self):
        fake = FakeWDS()
        fake.reverse = True
        self.assertTrue(collect.run(self.tmp, fetch=fake, now=T0)["ok"])
        s = self.doc("labour_force")["series"]
        self.assertEqual(s["vic.employment"]["coordinate"], "3.3.1.1.0.0.0.0.0.0")
        self.assertAlmostEqual(s["vic.employment"]["observations"]["2026-09-01"]["value"], 437.4, places=1)
        self.assertLess(s["vic.unemployment_rate"]["observations"]["2026-09-01"]["value"], 20)

    def test_unknown_label_fails_loudly_and_keeps_nothing_partial(self):
        cfg = json.loads((self.tmp / "config" / "series.json").read_text())
        cfg["datasets"][0]["measures"][0]["accept"] = ["Employment (persons)"]
        (self.tmp / "config" / "series.json").write_text(json.dumps(cfg))
        out = collect.run(self.tmp, fetch=FakeWDS(), now=T0)
        self.assertFalse(out["results"]["labour_force"]["ok"])
        self.assertIn("available:", out["results"]["labour_force"]["error"])
        self.assertTrue(out["results"]["vacancies"]["ok"])
        self.assertFalse((self.tmp / "data" / "official" / "labour_force.json").exists())


class Failures(Base):
    def test_outage_keeps_last_good_and_other_dataset_updates(self):
        collect.run(self.tmp, fetch=FakeWDS(), now=T0)
        before = (self.tmp / "data" / "official" / "labour_force.json").read_text()
        fake = FakeWDS(jv_latest="2026-07-01")   # a new quarter is published
        fake.fail.add("lfs")
        out = collect.run(self.tmp, fetch=fake, now=T1)
        self.assertFalse(out["ok"])
        self.assertEqual((self.tmp / "data" / "official" / "labour_force.json").read_text(), before)
        st = self.status()["datasets"]
        self.assertEqual(st["labour_force"]["lastResult"], "failed")
        self.assertEqual(st["labour_force"]["lastSuccess"], T0)
        self.assertEqual(st["labour_force"]["lastAttempt"], T1)
        self.assertEqual(st["vacancies"]["lastResult"], "ok")
        self.assertEqual(st["vacancies"]["lastSuccess"], T1)
        self.assertIn("2026-07-01", self.doc("vacancies")["series"]["vic.job_vacancies"]["observations"])

    def test_malformed_response_keeps_last_good(self):
        collect.run(self.tmp, fetch=FakeWDS(), now=T0)
        before = (self.tmp / "data" / "official" / "vacancies.json").read_text()
        fake = FakeWDS()
        fake.malformed.add("jv")
        out = collect.run(self.tmp, fetch=fake, now=T1)
        self.assertFalse(out["results"]["vacancies"]["ok"])
        self.assertTrue(out["results"]["labour_force"]["ok"])
        self.assertEqual((self.tmp / "data" / "official" / "vacancies.json").read_text(), before)
        self.assertEqual(self.status()["datasets"]["vacancies"]["lastResult"], "failed")

    def test_first_run_outage_creates_no_data(self):
        fake = FakeWDS()
        fake.fail.update({"lfs", "jv"})
        out = collect.run(self.tmp, fetch=fake, now=T0)
        self.assertFalse(out["ok"])
        self.assertFalse((self.tmp / "data" / "official" / "labour_force.json").exists())
        html = build.build(self.tmp, self.tmp / "data", self.tmp / "site", now=T0).read_text()
        self.assertIn("has not yet succeeded", html)
        self.assertIn("No official data", html)

    def test_codeset_outage_uses_cached_copy(self):
        collect.run(self.tmp, fetch=FakeWDS(), now=T0)
        fake = FakeWDS()
        fake.fail.add("codesets")
        out = collect.run(self.tmp, fetch=fake, now=T1)
        self.assertTrue(out["ok"])
        self.assertTrue(any("cached" in l for l in out["log"]))

    def test_valid_suppression_replaces_earlier_number(self):
        collect.run(self.tmp, fetch=FakeWDS(), now=T0)
        self.assertIsNotNone(self.doc("labour_force")["series"]["vic.unemployment_rate"]["observations"]["2026-09-01"]["value"])
        fake = FakeWDS()
        fake.overrides[(14100462, VIC_UR, "2026-09-01")] = {"value": None, "statusCode": 3}
        out = collect.run(self.tmp, fetch=fake, now=T1)
        self.assertTrue(out["ok"])
        o = self.doc("labour_force")["series"]["vic.unemployment_rate"]["observations"]["2026-09-01"]
        self.assertIsNone(o["value"])
        self.assertEqual(o["statusSymbol"], "x")
        html = build.build(self.tmp, self.tmp / "data", self.tmp / "site", now=T1).read_text()
        self.assertIn("Unavailable", html)


class RepeatAndRevision(Base):
    def test_same_input_rerun_creates_no_duplicates(self):
        collect.run(self.tmp, fetch=FakeWDS(), now=T0)
        n0 = self.count_obs("labour_force")
        data0 = (self.tmp / "data" / "official" / "labour_force.json").read_text()
        out = collect.run(self.tmp, fetch=FakeWDS(), now=T1)
        self.assertEqual(out["results"]["labour_force"]["added"], 0)
        self.assertEqual(out["results"]["labour_force"]["revisions"], 0)
        self.assertFalse(out["results"]["labour_force"]["changed"])
        self.assertEqual(self.count_obs("labour_force"), n0)
        self.assertEqual((self.tmp / "data" / "official" / "labour_force.json").read_text(), data0)
        self.assertEqual(self.status()["datasets"]["labour_force"]["lastSuccess"], T1)  # a check, not an observation

    def test_new_period_appends_and_old_history_is_retained(self):
        collect.run(self.tmp, fetch=FakeWDS(), now=T0)
        collect.run(self.tmp, fetch=FakeWDS(lfs_latest="2026-10-01"), now=T1)
        obs = self.doc("labour_force")["series"]["ca.employment"]["observations"]
        self.assertIn("2026-10-01", obs)
        self.assertIn("2023-10-01", obs)          # fell out of the 36-period window but kept
        self.assertEqual(len(obs), 37)

    def test_revision_updates_history_and_is_reported(self):
        collect.run(self.tmp, fetch=FakeWDS(), now=T0)
        fake = FakeWDS()
        fake.overrides[(14100441, VIC_JVR, "2025-10-01")] = {"value": 9.9}
        out = collect.run(self.tmp, fetch=fake, now=T1)
        self.assertEqual(out["results"]["vacancies"]["revisions"], 1)
        o = self.doc("vacancies")["series"]["vic.job_vacancy_rate"]["observations"]["2025-10-01"]
        self.assertEqual(o["value"], 9.9)
        self.assertEqual(o["lastChanged"], T1)
        self.assertEqual(o["firstRetrieved"], T0)
        report = (self.tmp / "reports" / "2026-W42.md").read_text()
        self.assertIn("vic.job_vacancy_rate", report)
        self.assertIn("→ 9.9", report)
        # a same-week rerun replaces the report but keeps the week's revision note
        collect.run(self.tmp, fetch=fake, now="2026-10-17T20:00:00Z")
        self.assertIn("→ 9.9", (self.tmp / "reports" / "2026-W42.md").read_text())
        # next week's report does not repeat it
        collect.run(self.tmp, fetch=fake, now=T2)
        self.assertIn("None detected.", (self.tmp / "reports" / "2026-W43.md").read_text())

    def test_report_week_uses_vancouver_time(self):
        from src.report import report_week
        # Monday 2026-10-19 03:00 UTC is still Sunday evening in Vancouver (week 42)
        self.assertEqual(report_week("2026-10-19T03:00:00Z"), "2026-W42")
        self.assertEqual(report_week("2026-10-19T08:00:00Z"), "2026-W43")


class BuildChecks(Base):
    def test_page_exposes_timestamps_without_js_and_escapes_labels(self):
        collect.run(self.tmp, fetch=FakeWDS(), now=T0)
        cfg = json.loads((self.tmp / "config" / "series.json").read_text())
        cfg["localSearch"]["places"].append("<script>alert(1)</script>")
        (self.tmp / "config" / "series.json").write_text(json.dumps(cfg))
        html = build.build(self.tmp, self.tmp / "data", self.tmp / "site", now=T0).read_text()
        self.assertIn(f'data-last-success="{T0}"', html)
        self.assertIn('data-stale-days="14"', html)
        self.assertIn("last successful check 10 Oct 2026", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Three-month average ending September 2026; not seasonally adjusted.", html)
        self.assertIn("Quarter: Q2 2026 (Apr–Jun); not seasonally adjusted.", html)
        self.assertIn("Individual advertisements are not collected in this release.", html)
        self.assertNotIn("SAMPLE DATA", html)
        self.assertTrue((self.tmp / "site" / "data" / "status.json").exists())

    def test_flagged_values_show_caution_text(self):
        fake = FakeWDS()
        fake.overrides[(14100441, VIC_JVR, "2026-04-01")] = {"statusCode": 4}
        collect.run(self.tmp, fetch=fake, now=T0)
        html = build.build(self.tmp, self.tmp / "data", self.tmp / "site", now=T0).read_text()
        self.assertIn("E · Use with caution", html)
        self.assertIn("E = use with caution", html)

    def test_rejects_non_https_links(self):
        cfg = json.loads((self.tmp / "config" / "series.json").read_text())
        cfg["localSearch"]["links"][0]["url"] = "javascript:alert(1)"
        (self.tmp / "config" / "series.json").write_text(json.dumps(cfg))
        with self.assertRaises(ValueError):
            build.build(self.tmp, self.tmp / "data", self.tmp / "site", now=T0)


if __name__ == "__main__":
    unittest.main()
