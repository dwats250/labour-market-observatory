"""Tiny server-side SVG line charts (no JavaScript, no dependencies)."""
from __future__ import annotations

import math
from html import escape

from . import metrics

W, H = 336, 168
L, R, T, B = 46, 46, 16, 30


def _nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    raw = (hi - lo) / max(1, n - 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    start = math.floor(lo / step) * step
    ticks, v = [], start
    while v <= hi + step * 0.5:
        ticks.append(round(v, 10))
        v += step
    return ticks


def _tick_text(v: float, step: float, kind: str) -> str:
    decimals = 0 if step >= 1 else 1 if step >= 0.1 else 2
    t = f"{v:,.{decimals}f}"
    return t + ("%" if kind == "rate" else "")


def line_chart(periods: list[str], obs: list[dict | None], *, kind: str, frequency: str, label: str) -> str:
    vals = [o["value"] if o and metrics.is_number(o.get("value")) else None for o in obs]
    nums = [v for v in vals if v is not None]
    aria = escape(f"{label}, {metrics.period_label(periods[0], frequency, True)} to "
                  f"{metrics.period_label(periods[-1], frequency, True)}" if periods else label, quote=True)
    if not nums:
        return (f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{aria}">'
                f'<text x="{W/2}" y="{H/2}" text-anchor="middle" class="ax">No values available</text></svg>')
    lo, hi = min(nums), max(nums)
    span = hi - lo or max(abs(hi) * 0.05, 0.5)
    ticks = _nice_ticks(lo - span * 0.08, hi + span * 0.08)
    ymin, ymax = ticks[0], ticks[-1]
    step = ticks[1] - ticks[0] if len(ticks) > 1 else 1
    n = len(periods)
    pw, ph = W - L - R, H - T - B

    def x(i):
        return L + (pw * i / (n - 1) if n > 1 else pw / 2)

    def y(v):
        return T + ph * (1 - (v - ymin) / (ymax - ymin))

    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{aria}">']
    for t in ticks:
        out.append(f'<line class="grid" x1="{L}" x2="{W-R}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="ax" x="{L-6}" y="{y(t)+3.5:.1f}" text-anchor="end">{escape(_tick_text(t, step, kind))}</text>')
    # x labels: first, middle, last
    for i in sorted({0, (n - 1) // 2, n - 1}):
        anchor = "start" if i == 0 and n > 1 else "end" if i == n - 1 and n > 1 else "middle"
        out.append(f'<text class="ax" x="{x(i):.1f}" y="{H-10}" text-anchor="{anchor}">'
                   f'{escape(metrics.period_label(periods[i], frequency, True))}</text>')
    # line segments split at gaps
    seg, paths, singles = [], [], []
    for i, v in enumerate(vals + [None]):
        if v is None:
            if len(seg) == 1:
                singles.append(seg[0])
            elif seg:
                paths.append("M" + " L".join(f"{x(j):.1f} {y(vals[j]):.1f}" for j in seg))
            seg = []
        else:
            seg.append(i)
    for p in paths:
        out.append(f'<path class="line" d="{p}"/>')
    for j in singles:
        out.append(f'<circle class="dot" cx="{x(j):.1f}" cy="{y(vals[j]):.1f}" r="3"/>')
    # caution markers
    for i, o in enumerate(obs):
        if vals[i] is not None and metrics.is_caution(o):
            out.append(f'<circle class="caution" cx="{x(i):.1f}" cy="{y(vals[i]):.1f}" r="4"/>'
                       f'<text class="flag" x="{x(i):.1f}" y="{y(vals[i])-8:.1f}" text-anchor="middle">E</text>')
    # end dot + direct label on latest numeric value
    last = max(i for i, v in enumerate(vals) if v is not None)
    lx, ly = x(last), y(vals[last])
    out.append(f'<circle class="end" cx="{lx:.1f}" cy="{ly:.1f}" r="4"/>')
    txt = metrics.format_value(obs[last], kind)
    out.append(f'<text class="val" x="{lx+8:.1f}" y="{ly+4:.1f}" text-anchor="start">{escape(txt)}</text>')
    # native hover titles on generous hit targets
    for i, v in enumerate(vals):
        tip = f"{metrics.period_label(periods[i], frequency)}: " + (
            metrics.format_value(obs[i], kind) if v is not None else "unavailable — " + metrics.unavailable_reason(obs[i]))
        if obs[i] and metrics.is_caution(obs[i]):
            tip += " (use with caution)"
        cy = y(v) if v is not None else T + ph / 2
        out.append(f'<circle class="hit" cx="{x(i):.1f}" cy="{cy:.1f}" r="9"><title>{escape(tip)}</title></circle>')
    out.append("</svg>")
    return "".join(out)
