"""Read the canonical JSON into a view model shared by the report and the site."""
from __future__ import annotations

import json
from pathlib import Path

from . import metrics


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def load(root: Path, data_dir: Path | None = None) -> dict:
    config = json.loads((root / "config" / "series.json").read_text(encoding="utf-8"))
    data_dir = data_dir or root / "data"
    status = _read(data_dir / "status.json") or {"datasets": {}, "revisions": []}
    datasets = {}
    for ds in config["datasets"]:
        datasets[ds["key"]] = {"cfg": ds, "doc": _read(data_dir / "official" / f"{ds['key']}.json"),
                               "status": status.get("datasets", {}).get(ds["key"], {})}
    return {"config": config, "status": status, "datasets": datasets}


def measure_view(ds: dict, geo_key: str, meas_cfg: dict) -> dict:
    """Current value, unit, period and comparison for one measure in one geography."""
    cfg, doc = ds["cfg"], ds["doc"]
    series = (doc or {}).get("series", {}).get(f"{geo_key}.{meas_cfg['key']}")
    view = {"key": meas_cfg["key"], "label": meas_cfg["label"], "kind": meas_cfg["kind"],
            "frequency": cfg["frequency"], "series": series, "available": False}
    if not series or not series.get("observations"):
        view["reason"] = "No official data collected yet"
        return view
    obs = series["observations"]
    ref = metrics.latest_period(obs)
    cur = obs[ref]
    exp = cur.get("scalarExponent", series.get("scalarExponent", 0))
    view.update(
        available=metrics.is_number(cur.get("value")),
        ref=ref,
        periodLabel=metrics.period_label(ref, cfg["frequency"]),
        obs=cur,
        valueText=metrics.format_value(cur, meas_cfg["kind"]),
        unit=metrics.unit_label(meas_cfg["kind"], series.get("uom"), series.get("scalarDesc"), exp),
        change=metrics.yoy_change(obs, ref, meas_cfg["kind"]),
        caution=metrics.is_caution(cur),
        flags=metrics.flag_symbols(cur),
        reason=None if metrics.is_number(cur.get("value")) else metrics.unavailable_reason(cur),
    )
    return view


def dataset_latest(ds: dict, geo_key: str) -> str | None:
    doc = ds["doc"] or {}
    refs = [max(s["observations"]) for k, s in doc.get("series", {}).items()
            if k.startswith(geo_key + ".") and s.get("observations")]
    return max(refs) if refs else None


def history(ds: dict, geo_key: str) -> dict:
    """Display window: latest N periods (gaps kept) for each measure in one geography."""
    cfg = ds["cfg"]
    latest = dataset_latest(ds, geo_key)
    if not latest:
        return {"periods": [], "rows": {}, "available": 0}
    window = metrics.period_window(latest, cfg["frequency"], cfg["displayPeriods"])
    series = (ds["doc"] or {}).get("series", {})
    rows = {}
    present = set()
    for m in cfg["measures"]:
        obs = (series.get(f"{geo_key}.{m['key']}") or {}).get("observations", {})
        rows[m["key"]] = [obs.get(p) for p in window]
        present.update(p for p in window if p in obs)
    first = min(present) if present else None
    if first:  # do not pad the start of a shorter published history with gaps
        window_trimmed = [p for p in window if p >= first]
        cut = len(window) - len(window_trimmed)
        window = window_trimmed
        rows = {k: v[cut:] for k, v in rows.items()}
    return {"periods": window, "rows": rows, "available": len(present)}
