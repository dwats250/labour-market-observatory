"""Shared measurement semantics: periods, scalars, flags and year-over-year changes.

Used by both the weekly report and the static site so the two can never disagree.
"""
from __future__ import annotations

import datetime as dt
import math
import re

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
MON3 = [m[:3] for m in MONTHS]

_SCALAR_WORDS = {
    "units": 0, "unit": 0, "tens": 1, "hundreds": 2, "thousands": 3,
    "tens of thousands": 4, "hundreds of thousands": 5, "millions": 6,
    "tens of millions": 7, "hundreds of millions": 8, "billions": 9,
}


# ---------------------------------------------------------------- periods

def parse_period(ref: str) -> dt.date:
    return dt.date.fromisoformat(ref[:10])


def same_period_last_year(ref: str) -> str:
    d = parse_period(ref)
    return d.replace(year=d.year - 1).isoformat()


def shift_period(ref: str, frequency: str, steps: int) -> str:
    """Move a reference period by `steps` months (monthly) or quarters."""
    d = parse_period(ref)
    months = steps * (3 if frequency == "quarterly" else 1)
    total = d.year * 12 + (d.month - 1) + months
    return dt.date(total // 12, total % 12 + 1, 1).isoformat()


def period_window(latest: str, frequency: str, n: int) -> list[str]:
    """The n consecutive periods ending at `latest`, oldest first (gaps included)."""
    return [shift_period(latest, frequency, -i) for i in range(n - 1, -1, -1)]


def quarter_of(d: dt.date) -> int:
    return (d.month - 1) // 3 + 1


def period_label(ref: str, frequency: str, short: bool = False) -> str:
    d = parse_period(ref)
    if frequency == "quarterly":
        q = quarter_of(d)
        if short:
            return f"Q{q} {d.year}"
        first = MONTHS[(q - 1) * 3][:3]
        last = MONTHS[(q - 1) * 3 + 2][:3]
        return f"Q{q} {d.year} ({first}–{last})"
    return f"{MON3[d.month - 1]} {d.year}" if short else f"{MONTHS[d.month - 1]} {d.year}"


# ---------------------------------------------------------------- scalars & values

def scalar_exponent(code: int | None, description: str | None = None) -> int:
    """Power of ten for a StatCan scalar factor. The code set description wins
    when it is recognisable; otherwise the WDS convention (code == exponent)."""
    if description:
        key = re.sub(r"\s+", " ", description.strip().lower())
        if key in _SCALAR_WORDS:
            return _SCALAR_WORDS[key]
    if code is None:
        return 0
    return int(code)


def to_absolute(value: float | None, exponent: int) -> float | None:
    if value is None:
        return None
    return value * (10 ** exponent)


def is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def format_number(value: float, decimals: int) -> str:
    return f"{value:,.{max(0, int(decimals))}f}"


def unit_label(kind: str, uom: str | None, scalar_desc: str | None, exponent: int) -> str:
    """Human unit text that never hides a source scalar."""
    if kind == "rate":
        return "percent"
    base = (uom or "number").strip()
    if exponent == 0:
        return base.lower()
    words = (scalar_desc or f"×10^{exponent}").strip().lower()
    return f"{base.lower()}, {words}"


def format_value(obs: dict | None, kind: str) -> str:
    if not obs or not is_number(obs.get("value")):
        return "Unavailable"
    text = format_number(obs["value"], obs.get("decimals", 1))
    return f"{text}%" if kind == "rate" else text


# ---------------------------------------------------------------- flags

def is_caution(obs: dict | None) -> bool:
    if not obs:
        return False
    for sym_key, desc_key in (("statusSymbol", "statusDesc"), ("symbolSymbol", "symbolDesc")):
        sym = (obs.get(sym_key) or "").strip()
        desc = (obs.get(desc_key) or "").lower()
        if sym == "E" or "use with caution" in desc:
            return True
    return False


def flag_symbols(obs: dict | None) -> list[tuple[str, str]]:
    """All non-empty status/symbol markers on an observation as (symbol, description)."""
    out = []
    if not obs:
        return out
    for sym_key, desc_key in (("statusSymbol", "statusDesc"), ("symbolSymbol", "symbolDesc")):
        sym = (obs.get(sym_key) or "").strip()
        if sym:
            out.append((sym, (obs.get(desc_key) or "").strip()))
    return out


def unavailable_reason(obs: dict | None) -> str:
    if obs is None:
        return "not published for this period"
    flags = flag_symbols(obs)
    if flags:
        return "; ".join(f"{s}: {d}" if d else s for s, d in flags)
    return "not available"


# ---------------------------------------------------------------- comparisons

def yoy_change(observations: dict, ref: str, kind: str) -> dict:
    """Change versus the same period one year earlier.

    rate  -> percentage-point difference
    count -> percent change on absolute (scalar-normalised) values
    Missing/suppressed values or a zero baseline give an unavailable result.
    """
    base_ref = same_period_last_year(ref)
    cur = observations.get(ref)
    base = observations.get(base_ref)
    result = {"available": False, "baseRef": base_ref, "kind": kind}
    if not cur or not is_number(cur.get("value")):
        result["reason"] = "current value unavailable"
        return result
    if not base or not is_number(base.get("value")):
        result["reason"] = "no comparable value one year earlier"
        return result
    if kind == "rate":
        delta = cur["value"] - base["value"]
        decimals = max(cur.get("decimals", 1), base.get("decimals", 1))
        delta = round(delta, decimals)
        result.update(available=True, delta=delta, unit="pp", decimals=decimals)
    else:
        a = to_absolute(cur["value"], cur.get("scalarExponent", 0))
        b = to_absolute(base["value"], base.get("scalarExponent", 0))
        if b == 0:
            result["reason"] = "baseline is zero"
            return result
        delta = round((a - b) / abs(b) * 100, 1)
        result.update(available=True, delta=delta, unit="%", decimals=1)
    result["direction"] = "up" if result["delta"] > 0 else "down" if result["delta"] < 0 else "flat"
    result["caution"] = is_caution(cur) or is_caution(base)
    return result


def format_change(change: dict) -> str:
    if not change.get("available"):
        return "Unavailable"
    d = change["delta"]
    sign = "+" if d > 0 else "−" if d < 0 else "±"
    mag = format_number(abs(d), change["decimals"])
    return f"{sign}{mag} pp" if change["unit"] == "pp" else f"{sign}{mag}%"


def arrow(change: dict) -> str:
    return {"up": "▲", "down": "▼", "flat": "▬"}.get(change.get("direction"), "")


def latest_period(observations: dict) -> str | None:
    """Latest reference period that has any record (numeric or explicitly unavailable)."""
    return max(observations) if observations else None
