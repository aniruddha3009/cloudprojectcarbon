# Measurement methodology

Every number on the dashboard carries a source label. A simulated value is never shown as live, and a missing live value is shown as unavailable, never filled in.

| Label | Meaning |
|---|---|
| `SIMULATED` | produced by the deterministic simulator (Simulation mode) |
| `MANUAL_OVERRIDE` | an operator-injected grid event (Simulation mode only) |
| `LIVE_ACTUAL` | a reading returned by India Energy Atlas (Live mode) |
| `LIVE_FORECAST` | an hourly forecast point returned by India Energy Atlas |
| `PERSISTENCE` | a future slot with no provider forecast: the latest real reading is held (stated in the UI) |
| `UNAVAILABLE` | no real reading has been received; Live scheduling waits |
| `ESTIMATED_MODEL` | simulation energy: declared power × runtime |
| `MEASURED_RAPL_ATTRIBUTED` | live energy: measured CPU-package energy × the job's share of busy CPU time |
| `ESTIMATED_CPU_TIME` | live fallback when no energy meter exists: job CPU-seconds × assumed watts per busy core |

## 1. Grid carbon intensity

**Simulation mode.** Hourly anchor values for three illustrative profiles (`solar_midday`, `windy_night`, `dirty_flat`), interpolated to 15-minute slots, with seeded ±3% Gaussian noise. They are shaped like a solar-heavy grid; they are not real data.

**Live mode: India Energy Atlas** (https://www.energymap.in/developer). Verified against the provider's documentation and with real HTTP calls on 28 October 2026:

| Item | Value |
|---|---|
| Latest reading | `GET https://api.energymap.in/developer/v1/carbon-intensity/latest` → `{"as_of", "scope", "intensity_gco2_per_kwh", "dominant_fuel"}` |
| Forecast | `GET /developer/v1/forecast/carbon-intensity?hours=24&order=asc` → `data.items[]` with `timestamp`, `carbon_intensity_gco2_kwh`, `is_forecast` (hourly) |
| Authentication | header `X-API-Key` (keys look like `iea_live_…`). A request without it returns `401 {"detail":{"code":"invalid_api_key","message":"Missing X-API-Key header"}}` (verified). |
| Coverage | national (all-India) on every key; `state=` needs a state-level plan (otherwise `402 feature_not_in_plan`) |
| Free plans | Sandbox (anyone) and Student (verified Indian academic email): 100 calls/day; Sandbox 3/min, Student 10/min |
| Provider update rate | grid data refreshed about every 15 minutes |
| Our polling | latest every 20 min (72 calls/day) plus forecast every 3 h (8/day), stopping at 95 calls/day |
| Accuracy (provider) | the fuel mix is **modelled** from SLDC demand, POSOCO availability and IEX schedules and calibrated weekly against CEA totals; expected error ±3% national, ±6% state |

How live slots get an intensity: each 30-second slot uses the latest real reading taken at or before the slot's start. Future slots use the provider forecast for that hour if one was returned, otherwise the latest reading held (`PERSISTENCE`). Forecast uncertainty is not modelled.

At the time of writing no API key was configured on the development laptop, so a successful authenticated reading has **not** yet been observed. The client is tested against the documented response formats, and the unauthenticated error format was confirmed live.

## 2. Workload energy

**Simulation mode (ESTIMATED).**
```
P(c)   = P_declared × (s + (1 − s)·c)          s = 0.30, c = capacity share
E_slot = P(c) × minutes / 60 / 1000             [kWh]
```
The declared powers (for example 1.5 kW for a GPU node) are plausible values, not measurements.

**Live mode (MEASURED, attributed).** Each managed workload is a real, bounded CPU task (SHA-256 hashing for at most 35% of one core at 100% capacity). For every 30-second slot:
```
package energy (J) = Δ Windows "Energy Meter(rapl_package0_pkg)\Energy"   (picowatt-hours × 3.6e-9)
job share          = job CPU-seconds ÷ all busy CPU-seconds on the machine (psutil)
job energy (J)     = package energy × job share
```
- **Measured:** the CPU-package energy (Intel RAPL, read through the Windows performance counter with the built-in PDH API; no admin rights needed), the job's own CPU time (`time.thread_time`), and the machine's busy CPU time.
- **Estimated:** the *share*. Proportional-to-CPU-time attribution ignores differences in how intensely different programs use the CPU, so it is labelled as attributed.
- **Not included:** memory, disk, screen, Wi-Fi and the rest of the laptop. RAPL covers the CPU package only.
- **Fallback:** if a PC has no energy meter, energy = CPU-seconds × `LIVE_CORE_WATTS` (12 W), labelled `ESTIMATED_CPU_TIME`.
- **Not used:** CPU % on its own (utilisation is not power), and battery discharge rate (whole-laptop, only available on battery).

Verified on the development laptop (Intel Core i5-13500H, Windows 11): the meter reported 7–16 W package power, and a managed job was attributed about 0.6–0.85 W over 1.2–1.8 s of CPU per 10-second slot.

## 3. Emissions, debt and credits

```
gross emissions = Σ_slots energy × intensity
debt            = Σ_slots energy × max(0, intensity − I_threshold)      I_threshold = 350 gCO₂e/kWh
credit          = max(0, E_full × I_baseline − gross emissions)          only if every eligibility check passes
```
These are kept separate everywhere: grid intensity, energy, gross emissions, policy debt and credits. Debt is a **policy** quantity. Credits count **future** emissions avoided by waiting; they never erase emissions that already happened.

Live-mode amounts are small (milligrams per job) because a laptop task uses joules, not kilowatt-hours. The accounting code is identical in both modes.

## 4. Laptop telemetry (Live mode)

`psutil` is read every ~2.5 s while monitoring is on: process name, PID, CPU % (change in CPU time ÷ elapsed time ÷ logical CPUs, like Task Manager), resident memory, status (refreshed every ~15 s because it is costly on Windows) and start time. Nothing else is read: no command lines, window titles or files. Ordinary programs are only observed; the scheduler controls only the workloads this app creates.

## 5. Precision and reproducibility

- Decimal arithmetic, quantised per slot with banker's rounding: energy 9 decimal places of kWh (3.6 mJ), carbon 6 decimal places of grams (1 µg), intensity 2 decimal places.
- Simulation and experiments are deterministic for a given seed. `tools/generate_results.py` regenerates every published number. The only non-deterministic metric is the measured decision time.
- Live results depend on real time and real data, so they are recorded, not replayed.

## Limitations

1. The cluster is simulated (4 workers on one laptop); there is no real cloud execution.
2. India Energy Atlas intensity is modelled by the provider, and the free plans are national only.
3. Live per-job energy is a CPU-time share of measured package energy, and it excludes non-CPU components.
4. Simulation energy is a declared-power model with a linear throttle model.
5. Forecast uncertainty is not modelled.
6. Hash-chain integrity depends on an externally kept head hash.
