"""Deterministic carbon-intensity curves at 15-minute resolution.

Simulated profiles are hourly anchor values (gCO2e/kWh) chosen to resemble a
grid with a strong solar midday dip and fossil-heavy morning/evening peaks.
They are *illustrative*, not data from a specific grid. Seeded multiplicative
noise (Gaussian, σ = noise_pct, clipped at ±2.5σ) adds realistic variation while
staying bit-for-bit reproducible for a given seed.

Every value carries a source label: SIMULATED, MANUAL_OVERRIDE or
LIVE_SNAPSHOT (a forecast captured from a real provider and replayed).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal

from .units import D, q_intensity

SLOT_MINUTES = 15
SLOTS_PER_HOUR = 60 // SLOT_MINUTES
SLOTS_PER_DAY = 24 * SLOTS_PER_HOUR

PROFILES: dict[str, list[int]] = {
    # 00 .. 23 h
    "solar_midday": [420, 400, 380, 360, 340, 320, 330, 620, 650, 560, 380, 220,
                     150, 130, 140, 210, 360, 520, 640, 680, 620, 540, 480, 440],
    "windy_night": [160, 140, 130, 140, 170, 230, 330, 450, 520, 540, 500, 460,
                    430, 420, 440, 480, 540, 600, 640, 610, 520, 400, 280, 200],
    "dirty_flat": [520, 510, 500, 495, 500, 520, 560, 600, 620, 610, 590, 570,
                   560, 555, 560, 575, 600, 630, 650, 640, 610, 580, 550, 530],
}

PROFILE_DESCRIPTIONS = {
    "solar_midday": "Fossil-heavy morning and evening peaks with a deep solar trough 11:30–15:00.",
    "windy_night": "Overnight wind surplus (green 21:00–05:00); fossil-heavy daytime.",
    "dirty_flat": "Stress test: no green window at all; repayment is impossible.",
}


@dataclass(frozen=True)
class CurvePoint:
    slot: int
    intensity: Decimal
    source: str


class CarbonCurve:
    def __init__(self, values: list[Decimal], sources: list[str], provider: str = "simulator", region: str = "SIM-GRID"):
        if not values:
            raise ValueError("carbon curve must not be empty")
        if len(values) != len(sources):
            raise ValueError("values and sources length mismatch")
        self.values = values
        self.sources = sources
        self.provider = provider
        self.region = region
        # Prefix sums for O(1) window averages in the planner.
        self._prefix: list[Decimal] = [Decimal(0)]
        for v in values:
            self._prefix.append(self._prefix[-1] + v)

    def __len__(self) -> int:
        return len(self.values)

    def _idx(self, slot: int) -> int:
        # Beyond the known horizon, repeat the last full day (documented assumption).
        if slot < len(self.values):
            return max(slot, 0)
        n = len(self.values)
        span = min(SLOTS_PER_DAY, n)
        return n - span + ((slot - n) % span)

    def at(self, slot: int) -> Decimal:
        return self.values[self._idx(slot)]

    def source_at(self, slot: int) -> str:
        return self.sources[self._idx(slot)]

    def window_avg(self, start: int, length: int) -> Decimal:
        if length <= 0:
            return self.at(start)
        if start >= 0 and start + length <= len(self.values):
            total = self._prefix[start + length] - self._prefix[start]
        else:
            total = sum((self.at(s) for s in range(start, start + length)), Decimal(0))
        return q_intensity(total / length)

    def window_max(self, start: int, length: int) -> Decimal:
        return max(self.at(s) for s in range(start, start + max(length, 1)))


def simulated_curve(
    profile: str = "solar_midday",
    seed: int = 42,
    noise_pct: Decimal | float = 3,
    days: int = 3,
    override: tuple[float, float, Decimal] | None = None,
    events: list[tuple[int, int, Decimal]] | None = None,
) -> CarbonCurve:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile}")
    anchors = PROFILES[profile]
    sigma = float(noise_pct) / 100.0
    values: list[Decimal] = []
    sources: list[str] = []
    for day in range(days):
        rng = random.Random(seed * 1009 + day)
        for slot in range(SLOTS_PER_DAY):
            hour, frac = divmod(slot, SLOTS_PER_HOUR)
            a = anchors[hour]
            b = anchors[(hour + 1) % 24]
            base = a + (b - a) * frac / SLOTS_PER_HOUR
            noise = max(-2.5 * sigma, min(2.5 * sigma, rng.gauss(0.0, sigma))) if sigma > 0 else 0.0
            values.append(q_intensity(D(round(base * (1.0 + noise), 4))))
            sources.append("SIMULATED")
    if override is not None:
        start_h, end_h, intensity = override
        for s in range(int(start_h * SLOTS_PER_HOUR), min(int(end_h * SLOTS_PER_HOUR), len(values))):
            values[s] = q_intensity(intensity)
            sources[s] = "MANUAL_OVERRIDE"
    # Presenter-set grid levels, applied in order (later events win where they overlap).
    for start, end, intensity in events or []:
        for s in range(max(start, 0), min(end, len(values))):
            values[s] = q_intensity(intensity)
            sources[s] = "MANUAL_OVERRIDE"
    return CarbonCurve(values, sources)


def curve_from_points(intensities: list[Decimal], source: str, provider: str, region: str) -> CarbonCurve:
    return CarbonCurve([q_intensity(v) for v in intensities], [source] * len(intensities), provider, region)
