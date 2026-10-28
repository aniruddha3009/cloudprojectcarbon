"""India Energy Atlas client (https://www.energymap.in/developer).

Documented endpoints used (verified against the provider's docs):
  GET {base}/developer/v1/carbon-intensity/latest            -> {"as_of", "scope", "intensity_gco2_per_kwh", "dominant_fuel"}
  GET {base}/developer/v1/forecast/carbon-intensity?hours=N  -> {"data": {"items": [{"timestamp", "carbon_intensity_gco2_kwh",
                                                                  "is_forecast", ...}], ...}, "meta": {...}}
Authentication: header ``X-API-Key`` (keys look like ``iea_live_...``).
Errors: ``{"detail": {"code": ..., "message": ...}}`` e.g. 401 ``invalid_api_key``, 402 ``feature_not_in_plan``.

Notes from the provider: the national figure is available on every key; ``state`` needs a state-level
plan. The fuel mix (and therefore intensity) is *modelled* by the provider from SLDC/IEX/POSOCO data
and calibrated weekly; expected error ±3 % national, ±6 % state. Free Sandbox/Student keys allow
100 calls per day, so this client is polled every ~20 minutes, never every few seconds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from ..config import Settings
from ..core.units import q_intensity

PROVIDER = "India Energy Atlas"
LATEST_PATH = "/developer/v1/carbon-intensity/latest"
FORECAST_PATH = "/developer/v1/forecast/carbon-intensity"


class ProviderError(RuntimeError):
    def __init__(self, message: str, code: str = "provider_error", status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class GridReading:
    intensity: Decimal
    as_of: datetime
    scope: str
    dominant_fuel: str | None
    fetched_at: datetime
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ForecastPoint:
    timestamp: datetime
    intensity: Decimal
    is_forecast: bool


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ProviderError("response has no valid timestamp", "bad_response")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderError(f"unparseable timestamp {value!r}", "bad_response") from exc
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _intensity(value: Any) -> Decimal:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 2000:
        raise ProviderError(f"implausible carbon intensity {value!r}", "bad_response")
    return q_intensity(value)


class IndiaEnergyAtlas:
    name = "india_energy_atlas"
    label = PROVIDER

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.base = settings.india_energy_atlas_base_url.rstrip("/")
        self.key = (settings.india_energy_atlas_api_key or "").strip() or None
        self.state = (settings.india_energy_atlas_state or "").strip() or None
        self.timeout = settings.provider_timeout_seconds
        self.client = client
        self.rate_limit: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        return self.key is not None

    @property
    def region(self) -> str:
        return f"India — {self.state}" if self.state else "India (national, all-India)"

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.key:
            raise ProviderError(
                "No API key configured. Set INDIA_ENERGY_ATLAS_API_KEY (in .env locally, or in the cloud service's "
                "environment settings), then restart the backend.", "missing_api_key")
        query = dict(params or {})
        if self.state:
            query["state"] = self.state
        try:
            getter = self.client.get if self.client is not None else httpx.get
            resp = getter(f"{self.base}{path}", params=query, timeout=self.timeout,
                          headers={"X-API-Key": self.key, "Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise ProviderError(f"{PROVIDER} is unreachable ({exc.__class__.__name__}). Check the internet connection.",
                                "unreachable") from exc
        self.rate_limit = {k: v for k, v in resp.headers.items() if k.lower().startswith("x-ratelimit")}
        try:
            body = resp.json()
        except ValueError:
            body = None
        if resp.status_code != 200:
            detail = body.get("detail") if isinstance(body, dict) else None
            code = detail.get("code") if isinstance(detail, dict) else None
            message = detail.get("message") if isinstance(detail, dict) else None
            hint = {
                401: "The API key was rejected. Check INDIA_ENERGY_ATLAS_API_KEY (no quotes or spaces) and that the key is not revoked.",
                402: "Your plan does not include this data (state-level data needs a state-level plan). Remove "
                     "INDIA_ENERGY_ATLAS_STATE to use the national figure.",
                403: "Access denied for this key (for example an IP allow-list).",
                429: "Rate limit reached. Free keys allow 100 calls per day; the app will retry later.",
            }.get(resp.status_code, "")
            raise ProviderError(f"HTTP {resp.status_code} {code or ''}: {message or 'request failed'}. {hint}".strip(),
                                code or f"http_{resp.status_code}", resp.status_code)
        if body is None:
            raise ProviderError(f"{PROVIDER} returned a non-JSON response", "bad_response")
        return body

    def latest(self) -> GridReading:
        body = self._get(LATEST_PATH)
        if not isinstance(body, dict):
            raise ProviderError("unexpected response shape", "bad_response")
        items = (body.get("data") or {}).get("items") if isinstance(body.get("data"), dict) else None
        if isinstance(items, list):
            # Shape actually returned by the live API (verified 2026-10-28): hourly rows, newest first,
            # each {"timestamp", "state", "carbon_intensity_gco2_kwh", "fuel_mix_mw": {...}, ...}.
            rows = [r for r in items if isinstance(r, dict) and r.get("carbon_intensity_gco2_kwh") is not None]
            if not rows:
                raise ProviderError("latest response has no readings in data.items", "bad_response")
            row = max(rows, key=lambda r: _parse_time(r.get("timestamp")))
            mix = row.get("fuel_mix_mw") if isinstance(row.get("fuel_mix_mw"), dict) else {}
            fuels = {k: v for k, v in mix.items() if isinstance(v, (int, float)) and k != "thermal"}
            return GridReading(
                intensity=_intensity(row.get("carbon_intensity_gco2_kwh")),
                as_of=_parse_time(row.get("timestamp")),
                scope=str(row.get("state") or ("state" if self.state else "national")),
                dominant_fuel=max(fuels, key=fuels.get) if fuels else None,
                fetched_at=datetime.now(timezone.utc),
                raw={k: row.get(k) for k in ("timestamp", "state", "carbon_intensity_gco2_kwh", "intensity_class",
                                             "total_generation_mw", "fuel_mix_mw")},
            )
        # Flat shape as written in the provider's documentation.
        return GridReading(
            intensity=_intensity(body.get("intensity_gco2_per_kwh")),
            as_of=_parse_time(body.get("as_of")),
            scope=str(body.get("scope") or ("state" if self.state else "national")),
            dominant_fuel=body.get("dominant_fuel"),
            fetched_at=datetime.now(timezone.utc),
            raw={k: body.get(k) for k in ("as_of", "scope", "intensity_gco2_per_kwh", "dominant_fuel")},
        )

    def forecast(self, hours: int = 24) -> list[ForecastPoint]:
        body = self._get(FORECAST_PATH, {"hours": hours, "order": "asc"})
        items = ((body or {}).get("data") or {}).get("items") if isinstance(body, dict) else None
        if not isinstance(items, list):
            raise ProviderError("forecast response has no data.items list", "bad_response")
        points = []
        for item in items:
            if not isinstance(item, dict) or item.get("carbon_intensity_gco2_kwh") is None:
                continue
            points.append(ForecastPoint(_parse_time(item.get("timestamp")), _intensity(item["carbon_intensity_gco2_kwh"]),
                                        bool(item.get("is_forecast", True))))
        return sorted(points, key=lambda p: p.timestamp)
