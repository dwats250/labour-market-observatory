"""Build the static dashboard into site/.

Usage:  python3 -m src.build [--root PATH] [--data DIR] [--out DIR] [--sample]

--sample marks every page as synthetic preview data; it is for local layout
checks only and is never used by the workflow.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from html import escape
from pathlib import Path

from . import charts, metrics, model

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("America/Vancouver")
except Exception:  # pragma: no cover
    _TZ = None

HERE = Path(__file__).resolve().parent
STALE_DAYS = 14


def e(s) -> str:
    return escape("" if s is None else str(s), quote=True)


def safe_url(u: str) -> str:
    if not isinstance(u, str) or not u.startswith("https://"):
        raise ValueError(f"refusing non-https URL in config: {u!r}")
    return e(u)


def when(ts: str | None) -> str:
    if not ts:
        return "never"
    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if _TZ:
        lt = t.astimezone(_TZ)
        return f"{lt.day} {metrics.MON3[lt.month-1]} {lt.year}, {lt:%H:%M} {lt.tzname()}"
    return f"{t:%Y-%m-%d %H:%M} UTC"


def release(ts: str | None) -> str:
    if not ts:
        return "not supplied"
    return ts.replace("T", " ")[:16] + " (Ottawa time, as published)"


# ---------------------------------------------------------------- fragments

def card(v: dict) -> str:
    if "ref" not in v:
        return (f'<div class="card empty"><div class="c-label">{e(v["label"])}</div>'
                f'<div class="c-value">—</div><div class="c-note">{e(v["reason"])}</div></div>')
    flags = ""
    if v["caution"]:
        flags += '<div class="c-flag">E · Use with caution</div>'
    other = [(s, d) for s, d in v["flags"] if s != "E"]
    if other:
        flags += "".join(f'<div class="c-flag">{e(s)}{" · " + e(d) if d else ""}</div>' for s, d in other)
    if v["available"]:
        value = f'<div class="c-value">{e(v["valueText"])}</div><div class="c-unit">{e(v["unit"])}</div>'
    else:
        value = f'<div class="c-value na">Unavailable</div><div class="c-unit">{e(v["reason"])}</div>'
    ch = v["change"]
    base = metrics.period_label(ch["baseRef"], v["frequency"], True)
    if ch["available"]:
        change = (f'<div class="c-change"><span class="arrow" aria-hidden="true">{metrics.arrow(ch)}</span> '
                  f'{e(metrics.format_change(ch))} <span class="muted">vs {e(base)}</span>'
                  f'{" <span class=muted>(includes flagged value)</span>" if ch.get("caution") else ""}</div>')
    else:
        change = f'<div class="c-change muted">Year-over-year: unavailable ({e(ch["reason"])})</div>'
    return f'<div class="card"><div class="c-label">{e(v["label"])}</div>{value}{change}{flags}</div>'


def group(ds: dict, geo_key: str) -> str:
    cfg = ds["cfg"]
    views = [model.measure_view(ds, geo_key, m) for m in cfg["measures"]]
    latest = model.dataset_latest(ds, geo_key)
    title = "Labour force" if cfg["frequency"] == "monthly" else "Job vacancies"
    if latest:
        period = cfg["periodNote"].format(period=metrics.period_label(latest, cfg["frequency"]))
    else:
        period = "No official data has been collected for this dataset yet."
    return (f'<div class="group g-{cfg["frequency"]}"><div class="g-head"><h3>{title}</h3>'
            f'<p class="period">{e(period)}</p></div>'
            f'<div class="cards n{len(views)}">{"".join(card(v) for v in views)}</div></div>')


def figure(ds: dict, geo_key: str, meas_key: str) -> str:
    cfg = ds["cfg"]
    meas = next(m for m in cfg["measures"] if m["key"] == meas_key)
    h = model.history(ds, geo_key)
    v = model.measure_view(ds, geo_key, meas)
    unit = v.get("unit", "")
    if not h["periods"]:
        body = '<p class="muted">No official data collected yet.</p>'
        span = ""
    else:
        body = charts.line_chart(h["periods"], h["rows"][meas_key], kind=meas["kind"],
                                 frequency=cfg["frequency"], label=meas["label"])
        p0 = metrics.period_label(h["periods"][0], cfg["frequency"], True)
        p1 = metrics.period_label(h["periods"][-1], cfg["frequency"], True)
        span = f"{p0} – {p1}"
        if len(h["periods"]) < cfg["displayPeriods"]:
            span += f" · only {len(h['periods'])} {'months' if cfg['frequency']=='monthly' else 'quarters'} published"
    avg = "3-month averages, " if cfg["frequency"] == "monthly" else "quarterly, "
    caution = any(o and metrics.is_caution(o) for o in h["rows"].get(meas_key, []))
    note = '<span class="fnote">Hollow point marked E: use with caution.</span>' if caution else ""
    return (f'<figure class="fig"><figcaption><strong>{e(meas["label"])}</strong>'
            f'<span class="muted">{e(unit)} · {avg}not seasonally adjusted</span>'
            f'<span class="muted">{e(span)}</span>{note}</figcaption>{body}</figure>')


def cell(o: dict | None, kind: str) -> str:
    if o is None:
        return '<td class="na">—</td>'
    if not metrics.is_number(o.get("value")):
        syms = " ".join(s for s, _ in metrics.flag_symbols(o)) or "n/a"
        return f'<td class="na">{e(syms)}</td>'
    flags = " ".join(s for s, _ in metrics.flag_symbols(o))
    txt = metrics.format_number(o["value"], o.get("decimals", 1))
    return f'<td>{e(txt)}{f" <sup>{e(flags)}</sup>" if flags else ""}</td>'


def table(ds: dict, geo_key: str) -> str:
    cfg = ds["cfg"]
    h = model.history(ds, geo_key)
    if not h["periods"]:
        return ""
    heads = []
    for m in cfg["measures"]:
        v = model.measure_view(ds, geo_key, m)
        heads.append(f'{e(m["label"])}<br><span class="muted">{e(v.get("unit", ""))}</span>')
    rows = []
    symbols = {}
    for i in range(len(h["periods"]) - 1, -1, -1):
        p = h["periods"][i]
        cells = []
        for m in cfg["measures"]:
            o = h["rows"][m["key"]][i]
            for s, d in metrics.flag_symbols(o):
                symbols[s] = d
            cells.append(cell(o, m["kind"]))
        rows.append(f'<tr><th scope="row">{e(metrics.period_label(p, cfg["frequency"], True))}</th>{"".join(cells)}</tr>')
    cap = ("Monthly — three-month moving averages ending in the month shown; not seasonally adjusted"
           if cfg["frequency"] == "monthly" else "Quarterly — not seasonally adjusted")
    legend = ""
    if symbols:
        legend = '<p class="fnote">' + " · ".join(
            f"{e(s)} = {e(d or 'see source table')}" + (" (use with caution)" if s == "E" and "caution" not in d.lower() else "")
            for s, d in sorted(symbols.items())) + "</p>"
    return (f'<div class="tbl"><table><caption>{e(cap)}</caption><thead><tr><th scope="col">Period</th>'
            + "".join(f'<th scope="col">{x}</th>' for x in heads)
            + f'</tr></thead><tbody>{"".join(rows)}</tbody></table>{legend}</div>')


def geo_section(m: dict, g: dict) -> str:
    lf, jv = m["datasets"]["labour_force"], m["datasets"]["vacancies"]
    region_note = ""
    if g["key"] == "vic":
        region_note = ('<p class="scope">Statistics Canada economic region. It covers Vancouver Island and adjacent '
                       'mainland coastal areas — it is not Nanaimo municipal data and not exactly Vancouver Island proper.</p>')
    hidden = "" if g.get("default") else " data-alt"
    return f"""
<section class="geo" id="geo-{e(g['key'])}" data-geo="{e(g['key'])}"{hidden} aria-labelledby="h-{e(g['key'])}">
  <h2 id="h-{e(g['key'])}">{e(g['label'])}</h2>
  {region_note}
  {group(lf, g['key'])}
  {group(jv, g['key'])}
  <h3 class="sub">History</h3>
  <div class="figs">
    {figure(lf, g['key'], 'employment')}
    {figure(lf, g['key'], 'unemployment_rate')}
    {figure(jv, g['key'], 'job_vacancy_rate')}
  </div>
  <details class="hist">
    <summary>Historical values — all five measures</summary>
    {table(lf, g['key'])}
    {table(jv, g['key'])}
  </details>
</section>"""


def status_block(m: dict) -> str:
    items, alerts = [], []
    for key, ds in m["datasets"].items():
        st, cfg = ds["status"], ds["cfg"]
        name = "Labour force (monthly)" if cfg["frequency"] == "monthly" else "Job vacancies (quarterly)"
        latest = st.get("latestReferencePeriod")
        items.append(
            f'<li data-dataset="{e(key)}" data-name="{e(name)}" data-last-success="{e(st.get("lastSuccess", ""))}">'
            f'<strong>{e(name)}</strong>: last successful check {e(when(st.get("lastSuccess")))}'
            f'{" · latest period " + e(metrics.period_label(latest, cfg["frequency"], True)) if latest else ""}</li>')
        if st.get("lastResult") == "failed":
            if st.get("lastSuccess"):
                alerts.append(f"The latest collection attempt for {name} failed ({when(st.get('lastAttempt'))}). "
                              f"Showing data from the last successful check ({when(st.get('lastSuccess'))}).")
            else:
                alerts.append(f"Collection for {name} has not yet succeeded; no official data is shown for it.")
        elif not st.get("lastSuccess"):
            alerts.append(f"No collection has run yet for {name}.")
    alert_html = "".join(f'<p class="alert" role="status">{e(a)}</p>' for a in alerts)
    return (f'<div class="fresh"><ul>{"".join(items)}</ul>'
            f'<p class="alert" id="overdue" role="alert" hidden></p>{alert_html}</div>')


def local_section(cfg: dict) -> str:
    ls = cfg["localSearch"]
    links = "".join(
        f'<li><a href="{safe_url(l["url"])}" rel="noopener">{e(l["name"])}</a><span>{e(l["how"])}</span></li>'
        for l in ls["links"])
    places = ", ".join(e(p) for p in ls["places"])
    fc = ls["forecast"]
    return f"""
<section class="local" aria-labelledby="h-local">
  <h2 id="h-local">Look locally</h2>
  <p class="lede">Individual advertisements are not collected in this release. Use these links to search current listings directly.</p>
  <ul class="links">{links}</ul>
  <p>Useful search locations: <strong>{places}</strong>. The links open each site's ordinary search page; they do not apply a location for you.</p>
  <p class="muted">Forecast, not an observation: <a href="{safe_url(fc['url'])}" rel="noopener">{e(fc['name'])}</a> — {e(fc['how'])}</p>
</section>"""


def sources_section(m: dict) -> str:
    parts = []
    for ds in m["datasets"].values():
        cfg, doc = ds["cfg"], ds["doc"] or {}
        rows = []
        for k, s in (doc.get("series") or {}).items():
            members = "; ".join(f"{dk}: {dv}" for dk, dv in s.get("members", {}).items())
            rows.append(f"<tr><td>{e(k)}</td><td>{e(s.get('vectorId'))}</td><td>{e(s.get('coordinate'))}</td><td>{e(members)}</td></tr>")
        resolved = ""
        if rows:
            resolved = ('<div class="tbl"><table class="small"><thead><tr><th>Series</th><th>Vector</th><th>Coordinate</th>'
                        f'<th>Published member labels</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
        parts.append(f"""
  <h3>Table {e(cfg['tableId'])}</h3>
  <p>{e(doc.get('title') or cfg['title'])}<br><a class="url" href="{safe_url(cfg['tableUrl'])}">{e(cfg['tableUrl'])}</a><br>
  <span class="muted">Source release: {e(release(doc.get('sourceReleaseTime')))}</span></p>
  {resolved}""")
    return f"""
<section class="sources" aria-labelledby="h-src">
  <details class="src">
    <summary id="h-src">Sources and method</summary>
    <ul class="method">
      <li>Employment is the estimated number of employed people, published in thousands. It is not a count of new jobs or hires.</li>
      <li>Labour force values are three-month moving averages, not seasonally adjusted. Consecutive months overlap.</li>
      <li>Changes compare the same period one year earlier: percentage points for rates, percent for counts. A comparison does not establish statistical significance or a cause.</li>
      <li>Job vacancies come from Statistics Canada's quarterly Job Vacancy and Wage Survey. It covers a defined population of employers, so the figure is not every available job. Quarters are never matched to a single labour-force month.</li>
      <li>Values marked E are to be used with caution. Missing or suppressed values are shown as unavailable and leave gaps in charts.</li>
      <li>History shown is the current revised official series; earlier retrieved versions are kept in the repository history. Regional figures are not allocated to towns.</li>
      <li>Employment, unemployment and vacancies are separate measures; no combined score is calculated.</li>
    </ul>
    {''.join(parts)}
    <p class="attr">Adapted from Statistics Canada, Tables 14-10-0462-01 and 14-10-0441-01 (reference periods as shown above). This does not constitute an endorsement by Statistics Canada of this product. Data used under the <a class="url" href="https://www.statcan.gc.ca/en/terms-conditions/open-licence">Statistics Canada Open Licence</a>.</p>
    <p class="noprint">Collected data: <a href="data/labour_force.json">labour_force.json</a> · <a href="data/vacancies.json">vacancies.json</a> · <a href="data/status.json">status.json</a></p>
  </details>
</section>"""


def page(m: dict, built: str, sample: bool) -> str:
    cfg = m["config"]
    geos = cfg["geographies"]
    css = (HERE / "assets" / "style.css").read_text(encoding="utf-8")
    js = (HERE / "assets" / "app.js").read_text(encoding="utf-8")
    radios = "".join(
        f'<label><input type="radio" name="geo" value="{e(g["key"])}"{" checked" if g.get("default") else ""}>'
        f'<span>{e(g["shortLabel"] if g["key"] != "vic" else "Vancouver Island & Coast")}</span></label>'
        for g in geos)
    sample_banner = ('<p class="sample">SAMPLE DATA — synthetic values for local layout preview. '
                     'These are not official statistics.</p>') if sample else ""
    return f"""<!doctype html>
<html lang="en-CA">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{"[SAMPLE] " if sample else ""}Labour Market Observatory</title>
<meta name="description" content="Regional employment conditions for Vancouver Island and Coast, British Columbia and Canada, with links to local job searches.">
<style>{css}</style>
</head>
<body data-stale-days="{STALE_DAYS}">
{sample_banner}
<header class="top">
  <h1>Labour Market Observatory</h1>
  <p class="subtitle">Regional conditions and local job-search links</p>
  {status_block(m)}
</header>
<div class="controls noprint">
  <fieldset class="seg"><legend>Statistical geography</legend>{radios}</fieldset>
  <button type="button" id="print">Print regional pulse</button>
</div>
<main>
{"".join(geo_section(m, g) for g in geos)}
{local_section(cfg)}
{sources_section(m)}
</main>
<footer><p>Page built {e(when(built))}. Weekly checks; Statistics Canada publishes labour force data monthly and vacancies quarterly.</p></footer>
<script>{js}</script>
</body>
</html>
"""


def build(root: Path, data_dir: Path, out: Path, sample: bool = False, now: str | None = None) -> Path:
    m = model.load(root, data_dir)
    now = now or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page(m, now, sample), encoding="utf-8")
    dd = out / "data"
    dd.mkdir(exist_ok=True)
    for name in ("labour_force", "vacancies"):
        src = data_dir / "official" / f"{name}.json"
        if src.exists():
            shutil.copyfile(src, dd / f"{name}.json")
    if (data_dir / "status.json").exists():
        shutil.copyfile(data_dir / "status.json", dd / "status.json")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return out / "index.html"


def main(argv=None) -> int:
    root_default = HERE.parent
    ap = argparse.ArgumentParser(description="Build the static dashboard.")
    ap.add_argument("--root", type=Path, default=root_default)
    ap.add_argument("--data", type=Path, default=None, help="data directory (default ROOT/data)")
    ap.add_argument("--out", type=Path, default=None, help="output directory (default ROOT/site)")
    ap.add_argument("--sample", action="store_true", help="label output as synthetic preview data")
    a = ap.parse_args(argv)
    path = build(a.root, a.data or a.root / "data", a.out or a.root / "site", a.sample)
    print(f"built {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
