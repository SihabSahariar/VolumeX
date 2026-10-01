"""Human-readable volume formatting."""
from __future__ import annotations

import math


def pct(value: float) -> str:
    return f"{round(value * 100)}%"


def db(value: float) -> str:
    if value <= 1e-4:
        return "−∞ dB"
    d = 20 * math.log10(value)
    if abs(d) < 0.05:
        return "0 dB"
    return f"{'+' if d > 0 else '−'}{abs(d):.1f} dB"


def gain_label(value: float) -> str:
    return f"{pct(value)}  ·  {db(value)}"
