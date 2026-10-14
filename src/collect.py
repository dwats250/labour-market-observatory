"""Weekly collector for the Labour Market Observatory.

Resolves each configured series from Statistics Canada WDS cube metadata by
published label, retrieves a bounded latest-N window, validates it, merges it
into the canonical JSON (recording revisions), and writes status + the weekly
Markdown report.

Each dataset is handled independently: a failure keeps that dataset's
last-good file and is recorded in data/status.json; the other dataset still
updates.

Usage:  python3 -m src.collect [--root PATH]
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import metrics, report

WDS_BASE = "https://www150.statcan.gc.ca/t1/wds/rest"
SCHEMA = 1
MAX_REVISION_LOG = 300


class FetchError(Exception):
    """Transport-level failure (network, HTTP status, unparseable body)."""


class ValidationError(Exception):
    """Payload arrived but is malformed or missing required series."""


# ---------------------------------------------------------------- transport

def http_fetch(method: str, endpoint: str, payload=None, *, timeout=30, attempts=3):
    """Call a WDS endpoint with bounded retries. Returns parsed JSON."""
    url = f"{WDS_BASE}/{endpoint}"
    data = None
    headers = {"Accept": "application/json",
               "User-Agent": "labour-market-observatory (+https://github.com/dwats250/labour-market-observatory)"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            try:
                return json.loads(body)
            except json.JSONDecodeError as e:
                raise FetchError(f"{endpoint}: response was not JSON ({e})") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
            if i < attempts - 1:
                time.sleep(2 * (i + 1))
    raise FetchError(f"{endpoint}: {last}")


# ---------------------------------------------------------------- helpers

def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(s: str | None) -> str:
    s = (s or "").replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, obj) -> bool:
    """Atomic write; returns True if content changed."""
    text = json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


def _wds_object(item, what: str):
    if not isinstance(item, dict) or item.get("status") != "SUCCESS" or not isinstance(item.get("object"), dict):
        raise ValidationError(f"{what}: WDS did not return SUCCESS ({str(item)[:200]})")
    return item["object"]


# ---------------------------------------------------------------- code sets

def _pick(entry: dict, suffixes: tuple[str, ...]):
    for k, v in entry.items():
        if any(k.endswith(s) for s in suffixes):
            return v
    return None


def parse_codesets(raw) -> dict:
    """Reduce WDS getCodeSets to {scalar,status,symbol,uom: {code: {symbol, desc}}}."""
    obj = raw.get("object") if isinstance(raw, dict) else None
    if not isinstance(obj, dict):
        raise ValidationError("getCodeSets: unexpected payload")
    out = {}
    for name in ("scalar", "status", "symbol", "uom"):
        table = {}
        for entry in obj.get(name) or []:
            if not isinstance(entry, dict):
                continue
            code = _pick(entry, ("Code",))
            if code is None:
                continue
            rep = _pick(entry, ("RepresentationEn",))
            desc = _pick(entry, ("DescEn",)) or (entry.get("memberUomEn") if name == "uom" else None)
            if name == "uom" and desc is None:
                desc = _pick(entry, ("En",))
            table[str(code)] = {"symbol": (rep or "").strip(), "desc": (desc or "").strip()}
        out[name] = table
    if not out["scalar"] or not out["status"]:
        raise ValidationError("getCodeSets: scalar/status code sets missing")
    return out


def load_codesets(fetch, official: Path, log: list[str]) -> dict:
    path = official / "codesets.json"
    try:
        cs = parse_codesets(fetch("GET", "getCodeSets"))
        write_json(path, cs)
        return cs
    except (FetchError, ValidationError) as e:
        cached = read_json(path)
        if cached:
            log.append(f"code sets: refresh failed ({e}); using cached copy")
            return cached
        raise


# ---------------------------------------------------------------- resolution

def pick_member(dim: dict, accept: list[str], what: str) -> dict:
    members = [m for m in dim.get("member") or [] if isinstance(m, dict)]
    by_name = {}
    for m in members:
        by_name.setdefault(norm(m.get("memberNameEn")), []).append(m)
    for a in accept:
        hits = by_name.get(norm(a))
        if hits and len(hits) == 1:
            return hits[0]
        if hits:
            raise ValidationError(f"{what}: label {a!r} is ambiguous in dimension {dim.get('dimensionNameEn')!r}")
    raise ValidationError(
        f"{what}: none of {accept} found in dimension {dim.get('dimensionNameEn')!r}; "
        f"available: {[m.get('memberNameEn') for m in members][:40]}")


def default_member(dim: dict, what: str) -> tuple[dict, str]:
    members = [m for m in dim.get("member") or [] if isinstance(m, dict)]
    if len(members) == 1:
        return members[0], "only member"
    roots = [m for m in members if m.get("parentMemberId") in (None, 0)
             and norm(m.get("memberNameEn")).startswith("total")]
    if len(roots) == 1:
        return roots[0], "aggregate root member"
    raise ValidationError(
        f"{what}: dimension {dim.get('dimensionNameEn')!r} has no configured selection; "
        f"members: {[m.get('memberNameEn') for m in members][:40]}")


def resolve_series(ds_cfg: dict, geos: list[dict], cube: dict) -> tuple[list[dict], list[str]]:
    """Map config labels to WDS coordinates. Returns (series specs, notes)."""
    dims = sorted(cube.get("dimension") or [], key=lambda d: d.get("dimensionPositionId", 0))
    if not dims:
        raise ValidationError(f"{ds_cfg['key']}: cube metadata has no dimensions")
    if len(dims) > 10:
        raise ValidationError(f"{ds_cfg['key']}: more than 10 dimensions")
    geo_dim = meas_dim = None
    fixed: dict[int, tuple[dict, str]] = {}
    notes = []
    for d in dims:
        name = norm(d.get("dimensionNameEn"))
        pos = d.get("dimensionPositionId")
        if re.search(ds_cfg["geographyDimension"], name):
            geo_dim = d
        elif re.search(ds_cfg["measureDimension"], name):
            meas_dim = d
        else:
            rule = next((r for r in ds_cfg.get("fixedDimensions", []) if re.search(r["dimension"], name)), None)
            if rule:
                fixed[pos] = (pick_member(d, rule["accept"], ds_cfg["key"]), "configured label")
            else:
                fixed[pos] = default_member(d, ds_cfg["key"])
            m, why = fixed[pos]
            notes.append(f"{d.get('dimensionNameEn')}: {m.get('memberNameEn')} ({why})")
    if geo_dim is None or meas_dim is None:
        raise ValidationError(f"{ds_cfg['key']}: geography or measure dimension not found in "
                              f"{[d.get('dimensionNameEn') for d in dims]}")
    specs = []
    for g in geos:
        gm = pick_member(geo_dim, g["accept"], f"{ds_cfg['key']}/{g['key']}")
        for meas in ds_cfg["measures"]:
            mm = pick_member(meas_dim, meas["accept"], f"{ds_cfg['key']}/{meas['key']}")
            chosen = {geo_dim["dimensionPositionId"]: (gm, geo_dim), meas_dim["dimensionPositionId"]: (mm, meas_dim)}
            for d in dims:
                if d["dimensionPositionId"] in fixed:
                    chosen[d["dimensionPositionId"]] = (fixed[d["dimensionPositionId"]][0], d)
            ids = [str(chosen[p][0]["memberId"]) if p in chosen else "0" for p in range(1, 11)]
            labels = {chosen[p][1].get("dimensionNameEn"): chosen[p][0].get("memberNameEn") for p in sorted(chosen)}
            uom = next((c[0].get("memberUomCode") for c in (chosen[meas_dim["dimensionPositionId"]],) if c[0].get("memberUomCode") is not None), None)
            if uom is None:
                uom = next((chosen[p][0].get("memberUomCode") for p in sorted(chosen) if chosen[p][0].get("memberUomCode") is not None), None)
            specs.append({
                "key": f"{g['key']}.{meas['key']}",
                "geo": g["key"], "measure": meas["key"], "kind": meas["kind"],
                "coordinate": ".".join(ids), "members": labels, "uomCode": uom,
            })
    return specs, notes


# ---------------------------------------------------------------- data points

def _code_info(codesets: dict, table: str, code) -> dict:
    if code is None:
        return {"symbol": "", "desc": ""}
    return codesets.get(table, {}).get(str(code), {"symbol": "", "desc": ""})


def normalise_points(spec: dict, obj: dict, codesets: dict, frequency: str) -> dict:
    points = obj.get("vectorDataPoint")
    if not isinstance(points, list) or not points:
        raise ValidationError(f"{spec['key']}: no data points returned")
    out = {}
    for p in points:
        if not isinstance(p, dict):
            raise ValidationError(f"{spec['key']}: malformed data point")
        ref = p.get("refPer")
        if not isinstance(ref, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ref[:10]):
            raise ValidationError(f"{spec['key']}: bad reference period {ref!r}")
        ref = ref[:10]
        d = metrics.parse_period(ref)
        if d.day != 1 or (frequency == "quarterly" and d.month not in (1, 4, 7, 10)):
            raise ValidationError(f"{spec['key']}: reference period {ref} does not fit {frequency} frequency")
        val = p.get("value")
        if val is not None and not metrics.is_number(val):
            raise ValidationError(f"{spec['key']}: non-numeric value {val!r} at {ref}")
        if ref in out:
            raise ValidationError(f"{spec['key']}: duplicate period {ref}")
        sc = p.get("scalarFactorCode")
        sc_info = _code_info(codesets, "scalar", sc)
        st = _code_info(codesets, "status", p.get("statusCode"))
        sy = _code_info(codesets, "symbol", p.get("symbolCode"))
        out[ref] = {
            "value": val,
            "decimals": int(p.get("decimals") or 0),
            "scalarFactorCode": sc,
            "scalarExponent": metrics.scalar_exponent(sc, sc_info.get("desc")),
            "statusCode": p.get("statusCode"), "statusSymbol": st["symbol"], "statusDesc": st["desc"],
            "symbolCode": p.get("symbolCode"), "symbolSymbol": sy["symbol"], "symbolDesc": sy["desc"],
            "securityLevelCode": p.get("securityLevelCode"),
            "releaseTime": p.get("releaseTime"),
        }
    return out


def _coord(c) -> tuple[int, ...]:
    parts = [int(x) for x in str(c).split(".") if x != ""]
    return tuple(parts + [0] * (10 - len(parts)))


def fetch_dataset(fetch, ds_cfg: dict, geos: list[dict], codesets: dict) -> dict:
    """Resolve, retrieve and validate one dataset. Raises on any failure."""
    meta = fetch("POST", "getCubeMetadata", [{"productId": ds_cfg["productId"]}])
    if not isinstance(meta, list) or not meta:
        raise ValidationError(f"{ds_cfg['key']}: getCubeMetadata returned no items")
    cube = _wds_object(meta[0], f"{ds_cfg['key']} metadata")
    specs, notes = resolve_series(ds_cfg, geos, cube)
    req = [{"productId": ds_cfg["productId"], "coordinate": s["coordinate"], "latestN": ds_cfg["latestN"]} for s in specs]
    raw = fetch("POST", "getDataFromCubePidCoordAndLatestNPeriods", req)
    if not isinstance(raw, list) or len(raw) != len(specs):
        raise ValidationError(f"{ds_cfg['key']}: expected {len(specs)} series, got "
                              f"{len(raw) if isinstance(raw, list) else type(raw).__name__}")
    # WDS does not promise response order: match each answer to its request by coordinate.
    by_coord = {}
    for item in raw:
        obj = _wds_object(item, ds_cfg["key"])
        if not obj.get("coordinate"):
            raise ValidationError(f"{ds_cfg['key']}: data response without a coordinate")
        by_coord[_coord(obj["coordinate"])] = obj
    series = {}
    for spec in specs:
        obj = by_coord.get(_coord(spec["coordinate"]))
        if obj is None:
            raise ValidationError(f"{spec['key']}: no data returned for coordinate {spec['coordinate']}")
        pts = normalise_points(spec, obj, codesets, ds_cfg["frequency"])
        latest = pts[max(pts)]
        sc_info = _code_info(codesets, "scalar", latest["scalarFactorCode"])
        uom = _code_info(codesets, "uom", spec["uomCode"])
        series[spec["key"]] = {
            "geo": spec["geo"], "measure": spec["measure"], "kind": spec["kind"],
            "vectorId": obj.get("vectorId"), "coordinate": spec["coordinate"],
            "members": spec["members"],
            "uomCode": spec["uomCode"], "uom": uom.get("desc") or None,
            "scalarFactorCode": latest["scalarFactorCode"], "scalarDesc": sc_info.get("desc") or None,
            "scalarExponent": latest["scalarExponent"],
            "_fetched": pts,
        }
    missing = [f"{g['key']}.{m['key']}" for g in geos for m in ds_cfg["measures"] if f"{g['key']}.{m['key']}" not in series]
    if missing:
        raise ValidationError(f"{ds_cfg['key']}: missing required series {missing}")
    return {"cube": {"title": cube.get("cubeTitleEn"), "releaseTime": cube.get("releaseTime"),
                     "cubeEndDate": cube.get("cubeEndDate")},
            "resolutionNotes": notes, "series": series}


# ---------------------------------------------------------------- merge

_COMPARE = ("value", "scalarFactorCode", "statusCode", "symbolCode")


def merge_dataset(existing: dict | None, fetched: dict, ds_cfg: dict, now: str) -> tuple[dict, list[dict], int]:
    """Merge a validated fetch into the stored document.

    Observations are keyed by series/reference period. Older periods outside the
    fetched window are retained. Changed values replace the stored ones and are
    returned as revisions; unchanged values are left untouched.
    """
    doc = copy.deepcopy(existing) if existing else {}
    doc.update({
        "schema": SCHEMA, "dataset": ds_cfg["key"], "productId": ds_cfg["productId"],
        "tableId": ds_cfg["tableId"], "title": fetched["cube"].get("title") or ds_cfg["title"],
        "tableUrl": ds_cfg["tableUrl"], "frequency": ds_cfg["frequency"],
        "resolutionNotes": fetched["resolutionNotes"],
    })
    if fetched["cube"].get("releaseTime"):
        doc["sourceReleaseTime"] = fetched["cube"]["releaseTime"]
    store = doc.setdefault("series", {})
    revisions, added = [], 0
    for key, s in fetched["series"].items():
        target = store.setdefault(key, {})
        observations = target.get("observations", {})
        meta = {k: v for k, v in s.items() if k != "_fetched"}
        if target.get("vectorId") not in (None, meta["vectorId"]):
            revisions.append({"series": key, "refPer": None, "detectedAt": now,
                              "note": f"vector changed {target.get('vectorId')} -> {meta['vectorId']}"})
        target.clear()
        target.update(meta)
        for ref, new in s["_fetched"].items():
            old = observations.get(ref)
            if old is None:
                observations[ref] = {**new, "firstRetrieved": now, "lastChanged": now}
                added += 1
            elif any(old.get(k) != new.get(k) for k in _COMPARE):
                revisions.append({
                    "dataset": ds_cfg["key"], "series": key, "refPer": ref, "detectedAt": now,
                    "old": {"value": old.get("value"), "status": old.get("statusSymbol") or old.get("symbolSymbol") or ""},
                    "new": {"value": new.get("value"), "status": new.get("statusSymbol") or new.get("symbolSymbol") or ""},
                })
                observations[ref] = {**new, "firstRetrieved": old.get("firstRetrieved", now), "lastChanged": now}
            else:
                # Same statistic: keep provenance, refresh only non-statistical metadata.
                observations[ref] = {**old, "decimals": new["decimals"], "releaseTime": new.get("releaseTime") or old.get("releaseTime"),
                                     "statusDesc": new["statusDesc"], "symbolDesc": new["symbolDesc"],
                                     "statusSymbol": new["statusSymbol"], "symbolSymbol": new["symbolSymbol"],
                                     "scalarExponent": new["scalarExponent"]}
        target["observations"] = dict(sorted(observations.items()))
    doc["series"] = dict(sorted(store.items()))
    return doc, revisions, added


# ---------------------------------------------------------------- run

def run(root: Path, fetch=http_fetch, now: str | None = None) -> dict:
    now = now or utc_now()
    config = json.loads((root / "config" / "series.json").read_text(encoding="utf-8"))
    official = root / "data" / "official"
    status_path = root / "data" / "status.json"
    status = read_json(status_path, {}) or {}
    status.setdefault("schema", SCHEMA)
    status.setdefault("datasets", {})
    status.setdefault("revisions", [])
    log: list[str] = []
    geos = config["geographies"]

    try:
        codesets = load_codesets(fetch, official, log)
        codeset_error = None
    except (FetchError, ValidationError) as e:
        codesets, codeset_error = None, e

    results = {}
    for ds_cfg in config["datasets"]:
        key = ds_cfg["key"]
        st = status["datasets"].setdefault(key, {})
        st["lastAttempt"] = now
        try:
            if codesets is None:
                raise FetchError(f"code sets unavailable: {codeset_error}")
            fetched = fetch_dataset(fetch, ds_cfg, geos, codesets)
            path = official / f"{key}.json"
            existing = read_json(path)
            doc, revisions, added = merge_dataset(existing, fetched, ds_cfg, now)
            changed = write_json(path, doc)
            st.update(lastResult="ok", lastSuccess=now, error=None,
                      latestReferencePeriod=max((max(s["observations"]) for s in doc["series"].values() if s.get("observations")), default=None))
            if changed:
                st["lastDataChange"] = now
            for r in revisions:
                r["dataset"] = key
            status["revisions"].extend(revisions)
            results[key] = {"ok": True, "added": added, "revisions": len(revisions), "changed": changed}
            log.append(f"{key}: ok — {added} new observations, {len(revisions)} revisions")
        except Exception as e:  # any failure keeps this dataset's last-good file
            if not isinstance(e, (FetchError, ValidationError)):
                e = ValidationError(f"unexpected {type(e).__name__}: {e}")
            st.update(lastResult="failed", error=str(e)[:500])
            results[key] = {"ok": False, "error": str(e)}
            log.append(f"{key}: FAILED — {e} (last-good data retained)")

    status["revisions"] = status["revisions"][-MAX_REVISION_LOG:]
    status["lastRun"] = now
    write_json(status_path, status)
    report_path = report.write_report(root, config, now)
    log.append(f"report: {report_path.relative_to(root)}")
    return {"ok": all(r["ok"] for r in results.values()), "results": results, "log": log}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=Path(__file__).resolve().parent.parent, type=Path)
    ap.add_argument("--strict", action="store_true", help="exit 1 if any dataset failed")
    args = ap.parse_args(argv)
    out = run(args.root)
    for line in out["log"]:
        print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Collection\n\n" + "\n".join(f"- {l}" for l in out["log"]) + "\n")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"collection_ok={'true' if out['ok'] else 'false'}\n")
    return 1 if (args.strict and not out["ok"]) else 0


if __name__ == "__main__":
    sys.exit(main())
