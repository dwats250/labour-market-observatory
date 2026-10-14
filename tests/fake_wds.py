"""In-memory stand-in for the Statistics Canada WDS, for tests and the local
sample preview only. Values are synthetic and must never be published as
official observations."""
from __future__ import annotations

import copy
import datetime as dt
import math

from src import metrics

CODESETS = {"status": "SUCCESS", "object": {
    "scalar": [{"scalarFactorCode": 0, "scalarFactorDescEn": "units"},
               {"scalarFactorCode": 3, "scalarFactorDescEn": "thousands"}],
    "status": [{"statusCode": 0, "statusRepresentationEn": "", "statusDescEn": ""},
               {"statusCode": 3, "statusRepresentationEn": "x", "statusDescEn": "suppressed to meet the confidentiality requirements of the Statistics Act"},
               {"statusCode": 4, "statusRepresentationEn": "E", "statusDescEn": "use with caution"},
               {"statusCode": 5, "statusRepresentationEn": "F", "statusDescEn": "too unreliable to be published"}],
    "symbol": [{"symbolCode": 0, "symbolRepresentationEn": "", "symbolDescEn": ""}],
    "uom": [{"memberUomCode": 249, "memberUomEn": "Persons"},
            {"memberUomCode": 239, "memberUomEn": "Percentage"},
            {"memberUomCode": 223, "memberUomEn": "Number"}],
}}

GEOS = [(1, "Canada", None), (2, "British Columbia", 1), (3, "Vancouver Island and Coast, British Columbia", 2),
        (4, "Lower Mainland-Southwest, British Columbia", 2)]


def _dim(pos, name, members):
    return {"dimensionPositionId": pos, "dimensionNameEn": name,
            "member": [{"memberId": mid, "memberNameEn": n, "parentMemberId": parent, "memberUomCode": uom}
                       for mid, n, parent, uom in members]}


LFS_META = {"status": "SUCCESS", "object": {
    "productId": "14100462", "cubeTitleEn": "Labour force characteristics by economic region, three-month moving average, unadjusted for seasonality",
    "releaseTime": "2026-10-09T08:30", "cubeEndDate": "2026-09-01",
    "dimension": [
        _dim(1, "Geography", [(i, n, p, None) for i, n, p in GEOS]),
        _dim(2, "Labour force characteristics", [(1, "Population", None, 249), (3, "Employment", None, 249),
                                                 (7, "Unemployment rate", None, 239), (9, "Employment rate", None, 239)]),
        _dim(3, "Gender", [(1, "Total - Gender", None, None), (2, "Men+", 1, None), (3, "Women+", 1, None)]),
        _dim(4, "Age group", [(1, "15 years and over", None, None), (2, "15 to 24 years", 1, None)]),
    ]}}

JV_META = {"status": "SUCCESS", "object": {
    "productId": "14100441", "cubeTitleEn": "Job vacancies, payroll employees, job vacancy rate, and average offered hourly wage by economic regions, quarterly, unadjusted for seasonality",
    "releaseTime": "2026-09-16T08:30", "cubeEndDate": "2026-04-01",
    "dimension": [
        _dim(1, "Geography", [(i, n, p, None) for i, n, p in GEOS]),
        _dim(2, "Statistics", [(1, "Job vacancies", None, 223), (2, "Payroll employees", None, 223),
                               (3, "Job vacancy rate", None, 239), (4, "Average offered hourly wage", None, 223)]),
    ]}}

BASE = {  # (level, amplitude) per geo id and measure id
    ("lfs", 1, 3): (20800.0, 300), ("lfs", 2, 3): (2850.0, 40), ("lfs", 3, 3): (437.0, 8),
    ("lfs", 1, 7): (6.8, 0.6), ("lfs", 2, 7): (6.0, 0.5), ("lfs", 3, 7): (5.4, 0.7),
    ("lfs", 1, 9): (61.0, 0.8), ("lfs", 2, 9): (60.5, 0.8), ("lfs", 3, 9): (55.8, 1.0),
    ("jv", 1, 1): (520000.0, 40000), ("jv", 2, 1): (75000.0, 6000), ("jv", 3, 1): (8200.0, 900),
    ("jv", 1, 3): (2.9, 0.3), ("jv", 2, 3): (3.3, 0.3), ("jv", 3, 3): (3.6, 0.4),
}


class FakeWDS:
    """Callable with the same signature as collect.http_fetch."""

    def __init__(self, lfs_latest="2026-09-01", jv_latest="2026-04-01"):
        self.lfs_latest, self.jv_latest = lfs_latest, jv_latest
        self.fail = set()          # {"lfs", "jv", "codesets"} -> raise transport error
        self.malformed = set()     # {"lfs", "jv"} -> return a broken payload
        self.overrides = {}        # (pid, coordinate, refPer) -> dict of datapoint fields
        self.calls = []

    def __call__(self, method, endpoint, payload=None):
        from src.collect import FetchError
        self.calls.append(endpoint)
        if endpoint == "getCodeSets":
            if "codesets" in self.fail:
                raise FetchError("simulated outage")
            return copy.deepcopy(CODESETS)
        pid = payload[0]["productId"]
        tag = "lfs" if pid == 14100462 else "jv"
        if tag in self.fail:
            raise FetchError(f"simulated outage for {pid}")
        if endpoint == "getCubeMetadata":
            return [copy.deepcopy(LFS_META if tag == "lfs" else JV_META)]
        if tag in self.malformed:
            return [{"status": "SUCCESS", "object": {"vectorDataPoint": [{"refPer": "garbage", "value": "n/a"}]}}]
        return [self._series(tag, req) for req in payload]

    def _series(self, tag, req):
        ids = [int(x) for x in req["coordinate"].split(".")]
        geo, meas = ids[0], ids[1]
        level, amp = BASE[(tag, geo, meas)]
        freq = "monthly" if tag == "lfs" else "quarterly"
        latest = self.lfs_latest if tag == "lfs" else self.jv_latest
        refs = metrics.period_window(latest, freq, req["latestN"])
        rate = (tag, meas) in (("lfs", 7), ("lfs", 9), ("jv", 3))
        pts = []
        for i, ref in enumerate(refs):
            d = dt.date.fromisoformat(ref)
            season = math.sin((d.month / 12) * 2 * math.pi) * amp
            trend = i * amp * 0.03 * (1 if meas != 7 else 0.5)
            val = round(level + season + trend, 1)
            if tag == "jv" and not rate:
                val = round(val)
            pt = {"refPer": ref, "refPer2": "", "value": val, "decimals": 1 if (rate or tag == "lfs") else 0,
                  "scalarFactorCode": 3 if (tag == "lfs" and not rate) else 0,
                  "symbolCode": 0, "statusCode": 0, "securityLevelCode": 0,
                  "releaseTime": "2026-10-09T08:30" if tag == "lfs" else "2026-09-16T08:30",
                  "frequencyCode": 6 if tag == "lfs" else 9}
            pt.update(self.overrides.get((req["productId"], req["coordinate"], ref), {}))
            pts.append(pt)
        return {"status": "SUCCESS", "object": {
            "responseStatusCode": 0, "productId": req["productId"], "coordinate": req["coordinate"],
            "vectorId": 100000 + req["productId"] % 1000 * 100 + geo * 10 + meas,
            "vectorDataPoint": pts}}
