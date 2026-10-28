"""Decimal-safe numeric helpers and rounding rules for carbon accounting.

Rounding rules (documented in docs/MEASUREMENT_METHODOLOGY.md):
  * energy            -> kWh, 9 decimal places (1 µWh = 3.6 mJ resolution; Live-mode laptop jobs use only joules)
  * carbon intensity  -> gCO2e/kWh, 2 decimal places
  * carbon mass       -> gCO2e, 6 decimal places (1 µg resolution)
  * power             -> W, 3 decimal places
All quantisation uses banker's rounding (ROUND_HALF_EVEN). Values are quantised
per 15-minute execution slot and then summed, so totals are reproducible
bit-for-bit across runs and platforms.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, Decimal, getcontext
from typing import Union

getcontext().prec = 28

Number = Union[Decimal, int, float, str]

ZERO = Decimal("0")
ONE = Decimal("1")

_KWH_Q = Decimal("0.000000001")
_G_Q = Decimal("0.000001")
_INTENSITY_Q = Decimal("0.01")
_W_Q = Decimal("0.001")


def D(value: Number) -> Decimal:
    """Convert to Decimal via str() so floats do not leak binary artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite numbers are not allowed in carbon accounting")
    return Decimal(str(value))


def q_kwh(value: Number) -> Decimal:
    return D(value).quantize(_KWH_Q, rounding=ROUND_HALF_EVEN)


def q_g(value: Number) -> Decimal:
    return D(value).quantize(_G_Q, rounding=ROUND_HALF_EVEN)


def q_intensity(value: Number) -> Decimal:
    return D(value).quantize(_INTENSITY_Q, rounding=ROUND_HALF_EVEN)


def q_w(value: Number) -> Decimal:
    return D(value).quantize(_W_Q, rounding=ROUND_HALF_EVEN)


def to_float(value: Decimal | None) -> float | None:
    """For JSON responses / charts only — never for accounting."""
    return None if value is None else float(value)
