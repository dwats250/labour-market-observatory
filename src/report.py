"""Weekly Markdown check report (a reading copy; never parsed back as data)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import metrics, model

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("America/Vancouver")
except Exception:  # pragma: no cover - tz database missing
    _TZ = dt.timezone(dt.timedelta(hours=-8))


def report_week(now_utc: str) -> str:
    """ISO week of the run in America/Vancouver, e.g. 2026-W42."""
    t = dt.datetime.fromisoformat(now_utc.replace("Z", "+00:00")).astimezone(_TZ)
    y, w, _ = t.isocalendar()
    return f"{y}-W{w:02d}"


def _md(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def render(root: Path, config: dict, now: str) -> str:
    m = model.load(root)
    week = report_week(now)
    lines = [f"# Labour Market Observatory — weekly check {week}", "",
             f"Run: {now} (UTC). Report week = ISO week in America/Vancouver.", "",
             "## Collection status", "",
             "| Dataset | Table | Last attempt | Result | Last successful check | Latest reference period |",
             "|---|---|---|---|---|---|"]
    for key, ds in m["datasets"].items():
        st, cfg = ds["status"], ds["cfg"]
        latest = st.get("latestReferencePeriod")
        lines.append("| " + " | ".join(_md(x) for x in [
            key, cfg["tableId"], st.get("lastAttempt", "—"),
            st.get("lastResult", "never run") + (f" — {st['error']}" if st.get("error") else ""),
            st.get("lastSuccess", "never"),
            metrics.period_label(latest, cfg["frequency"]) if latest else "—"]) + " |")
    lines.append("")
    for g in config["geographies"]:
        lines += [f"## {g['label']}", "",
                  "| Measure | Value | Unit | Reference period | Change vs same period a year earlier | Flags |",
                  "|---|---|---|---|---|---|"]
        for ds in m["datasets"].values():
            for meas in ds["cfg"]["measures"]:
                v = model.measure_view(ds, g["key"], meas)
                if "ref" not in v:
                    lines.append(f"| {_md(meas['label'])} | — | — | — | — | {_md(v['reason'])} |")
                    continue
                flags = "; ".join(f"{s} ({d})" if d else s for s, d in v["flags"])
                if v["caution"] and "caution" not in flags.lower():
                    flags = (flags + "; " if flags else "") + "use with caution"
                period = v["periodLabel"] + (" (3-month avg, NSA)" if ds["cfg"]["frequency"] == "monthly" else " (NSA)")
                change = metrics.format_change(v["change"])
                if not v["change"]["available"]:
                    change += f" ({v['change']['reason']})"
                value = v["valueText"] if v["available"] else f"Unavailable ({v['reason']})"
                lines.append("| " + " | ".join(_md(x) for x in [meas["label"], value, v["unit"], period, change, flags or "—"]) + " |")
        lines.append("")
    revs = [r for r in m["status"].get("revisions", []) if r.get("detectedAt") and report_week(r["detectedAt"]) == week]
    lines += ["## Revisions detected this week", ""]
    if revs:
        for r in revs:
            if r.get("refPer"):
                lines.append(f"- {r.get('dataset')} `{r['series']}` {r['refPer']}: "
                             f"{r['old']['value']} {r['old']['status']} → {r['new']['value']} {r['new']['status']} (detected {r['detectedAt']})")
            else:
                lines.append(f"- {r.get('dataset')} `{r['series']}`: {r.get('note')} (detected {r['detectedAt']})")
    else:
        lines.append("None detected.")
    lines += ["", "## Source", ""]
    for ds in m["datasets"].values():
        cfg = ds["cfg"]
        lines.append(f"- Adapted from Statistics Canada, Table {cfg['tableId']} {cfg['title']}. {cfg['tableUrl']}")
    lines += ["", "This does not constitute an endorsement by Statistics Canada of this product.", ""]
    return "\n".join(lines)


def write_report(root: Path, config: dict, now: str) -> Path:
    path = root / "reports" / f"{report_week(now)}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(root, config, now), encoding="utf-8")
    return path
