# Learning guide: understand Carbon Debt Computing

This guide explains the project in plain English. Read it once from top to bottom before the viva.

---

## 1. The problem and the idea

Electricity is not equally "dirty" all day. When the grid burns a lot of coal, each kWh produces more CO₂ (high **carbon intensity**, measured in gCO₂e/kWh). When there is a lot of solar or wind, each kWh produces less.

Some computer work is **urgent** (an emergency): it must run now, even if the grid is dirty. Other work is **flexible**: it can wait a few hours.

**Our idea:** when urgent work has to run on dirty electricity, we write down the extra carbon as a **debt**. While the debt is unpaid, flexible work is moved to clean ("green") periods. Each time flexible work runs cleaner than it would have run, it earns a **credit** that pays back the debt. Everything is recorded in a tamper-evident **ledger**.

> **Important:** a credit does not undo past emissions. It records emissions we *avoided later* by waiting for cleaner power.

---

## 2. The two modes

| | Simulation mode | Live mode |
|---|---|---|
| Purpose | Controlled, repeatable demonstration and experiments | Real data from the real world |
| Grid intensity | Simulated curve (labelled SIMULATED) | **India Energy Atlas** API (all-India reading) |
| Energy | Estimated: declared power × time | **Measured** CPU-package energy (Windows Energy Meter), shared out by CPU time |
| Time | A simulated clock, 15-minute slots | Real time, 30-second slots |
| Workloads | Simulated jobs | Small, bounded CPU tasks the app really runs |
| Windows processes | Not shown | Listed every ~2.5 s (watched only, never controlled) |
| Needs internet / API key | No | Yes for the grid reading (process monitoring works without it) |

The two modes use **separate databases** (`backend/data/carbon_debt.db` and `carbon_debt_live.db`), so simulated and real records never mix.

---

## 3. The ten features, and where each one lives

| # | Feature | What it does | Main file |
|---|---|---|---|
| 1 | Carbon-debt engine | Runs time in slots (15 min in simulation, 30 s in live). Computes energy, emissions and debt with exact decimals. | `backend/app/core/engine.py`, `core/accounting.py`, `core/units.py` |
| 2 | Carbon-debt ledger | Records every debt, deferral, credit and "debt cleared" event with its numbers. | `core/ledger.py` |
| 3 | Priority inversion and green repayment | While debt > 0, flexible jobs may run only in green slots (≤ 200 g/kWh), ranked by how much debt they repay. | `core/policies.py` (debt controllers), `core/planner.py` |
| 4 | Progressive throttling | Debt bands slow background and normal jobs to 50%, 20% or pause, never emergencies, never past a deadline. | `core/policies.py` → `apply_throttle`, `THROTTLE_TABLE` |
| 5 | Emergency precedence | Emergencies start immediately; one worker is always reserved for them. | `core/policies.py` → `admit_emergencies` |
| 6 | Deadline safety | Jobs are only delayed into windows that still finish before the deadline (2-slot safety margin, repair pass). | `core/planner.py`, `policies.min_feasible_capacity` |
| 7 | Predictive controller | Uses the forecast to pick the cleanest feasible window and project future debt. | `core/planner.py` |
| 8 | Verified credits | A credit is given only if the job was deliberately deferred, its baseline was recorded, it finished on time, and it was never credited before. | `core/accounting.py` → `evaluate_credit` |
| 9 | Hash-chained audit ledger | Each entry stores SHA-256 of its contents plus the previous entry's hash; the chain can be verified and tampering detected. | `core/hashchain.py` |
| 10 | Receipts and state machine | Each finished job gets a JSON carbon receipt. Job states follow fixed rules; invalid moves are rejected. | `services/simulation.py` → `_receipt`, `core/engine.py` → `ALLOWED_TRANSITIONS` |

Other important files:

| File | Purpose |
|---|---|
| `services/live.py` | Live mode: real-time slots, bounded CPU workers, measured energy, India Energy Atlas polling |
| `services/india_energy_atlas.py` | The API client (documented endpoints only) |
| `services/system_monitor.py` | Windows process list, CPU/memory, energy meter |
| `services/modes.py` | Switches between Simulation and Live |
| `core/experiment.py` | Replays identical inputs under the four policies |
| `frontend/src/pages/*.tsx` | The six dashboard pages |

---

## 4. How the scheduler decides: run or wait?

Every slot, for every waiting job:

1. **Is it an emergency?** Then run it now. Done.
2. **Is there carbon debt?**
   - **Yes:** flexible work should run only in a **green** slot (≤ 200 g/kWh). If no green slot fits before the deadline, it runs in the *least dirty* slot that still meets the deadline.
   - **No:** run now unless a clearly cleaner slot is coming that still meets the deadline (and the saving is worth the delay).
3. **Would waiting miss the deadline?** Then run now ("deadline-forced"). Deadlines always win over carbon.
4. **Is debt high?** Running flexible jobs are slowed (throttled) according to the debt band, but only if they can still finish two slots before their deadline.

The reason for every decision is saved in plain words. Open any workload to read "Why".

---

## 5. The formulas, with a worked example

```
energy (kWh)      = power (W) × time (h) / 1000
emissions (g)     = energy × grid intensity
debt (g)          = energy × max(0, intensity − 350)
credit (g)        = max(0, energy × baseline intensity − actual emissions)
outstanding debt  = all debt − all credits applied   (never below 0)
```

**Worked example.** An emergency job uses 1.5 kW for 1 hour while the grid is at 600 g/kWh.

- Energy = 1,500 W × 1 h / 1,000 = **1.5 kWh**
- Emissions = 1.5 × 600 = **900 g**
- Debt = 1.5 × (600 − 350) = **375 g**: only the part above the threshold is "debt".

A flexible job (1 kWh) was due to run at 630 g/kWh (its **baseline**, recorded when it was deferred), but waited and ran at 140 g/kWh:

- Actual emissions = 1 × 140 = 140 g
- Credit = 1 × 630 − 140 = **490 g**, so the outstanding debt falls from 375 g to 0 g.
- The extra 115 g is **not banked**: you cannot save credit for future emergencies.

All maths uses exact decimals (energy to 9 decimal places of kWh, carbon to 6 decimal places of grams), so results are identical every run.

---

## 6. How the India Energy Atlas integration works

- **Endpoint:** `GET https://api.energymap.in/developer/v1/carbon-intensity/latest`. It returns `intensity_gco2_per_kwh`, `as_of` (time) and `scope` (national or state).
- **Forecast:** `GET /developer/v1/forecast/carbon-intensity?hours=24`, hourly.
- **Authentication:** the backend sends your key in the `X-API-Key` header. The key stays in `.env` on your computer and is never sent to the browser.
- **How often:** free keys allow **100 calls per day**, so the app asks every **20 minutes** (72/day) plus a forecast every 3 hours (8/day). The provider updates about every 15 minutes, so polling faster would only waste quota.
- **If it fails:** the dashboard shows the provider's own error message (for example "Invalid API key"). The app **never** puts in a made-up value.
- **What the number means:** the provider *models* India's fuel mix from SLDC/IEX/POSOCO data (expected error ±3% national). It is the best public figure, not a meter on the grid.
- **Coverage:** the free plans give the **all-India** figure. State-level data needs a state-level plan.

---

## 7. How Windows monitoring works

- **Processes:** every ~2.5 s the backend uses the Python library `psutil` to list running programs (name, PID, CPU %, memory, status, start time). It reads nothing else: no window titles, files or command lines. It never pauses or closes anything.
- **CPU % like Task Manager:** the change in each process's CPU time divided by elapsed time and the number of CPU cores.
- **Energy:** Windows has an "Energy Meter" performance counter that exposes Intel's **RAPL** CPU-package energy (on this laptop, ~6–16 W). We read it through Windows' built-in PDH library. It needs no admin rights.
- **A job's share:** package energy covers *all* programs, so each managed job gets `package energy × (job's CPU time ÷ all busy CPU time)`. The total is measured; the share is an estimate, and it is labelled that way.
- **Not used for energy:** CPU % alone (that is not power), and battery discharge (it is whole-laptop and only works on battery).

---

## 8. What the database stores

| Table | Holds |
|---|---|
| `jobs` | each workload: class, deadline, state, energy, emissions, debt, credit |
| `decisions` | every scheduler decision with its reason |
| `execution_attempts` | one row per job per slot: capacity, energy, intensity, CPU time, energy source |
| `ledger_entries` | the hash-chained debt/credit ledger |
| `timeline_points`, `carbon_readings` | data for the charts |
| `grid_readings` (live DB) | every real India Energy Atlas reading and forecast point |
| `experiment_runs` (simulation DB) | saved experiment settings and results |
| `settings`, `sim_clock` | controller settings, active mode, clock |

---

## 9. The four scheduling policies

| Policy | In one sentence |
|---|---|
| FIFO | Runs jobs as soon as a worker is free and ignores carbon (the baseline). |
| Threshold | Waits while the grid is above 350 g/kWh, unless the deadline forces it to run. |
| Debt controller | Threshold, plus debt: while in debt, flexible work only runs in green slots, and throttling depends on debt. No forecast. |
| Predictive controller | The debt controller plus a forecast planner that books the cleanest slot that still meets every deadline. |

Results from 10 simulated runs: the predictive controller cut emissions by about 17% and debt by about 46% compared with FIFO, with the same deadline misses as the threshold policy. The cost is that flexible jobs finish later. See `docs/EXPERIMENTS.md`.

---

## 10. What is live, measured, estimated or simulated

| Quantity | Simulation mode | Live mode |
|---|---|---|
| Grid intensity | SIMULATED | LIVE (India Energy Atlas, modelled by the provider) |
| Grid forecast | the simulated curve | provider forecast if your plan returns one; otherwise "PERSISTENCE" (latest reading held) |
| Job energy | ESTIMATED (declared power) | MEASURED package energy, shared by CPU time (or ESTIMATED from CPU time if no meter) |
| CPU time of jobs | small real proxy kernel | MEASURED per job |
| Processes, CPU %, memory | — | MEASURED (psutil) |
| Debt, credits | policy calculation | policy calculation |
| Experiments | always simulated, identical inputs | (experiments always use simulation) |

---

## 11. How to run and demonstrate

```powershell
cd "C:\Users\bomba\OneDrive\Desktop\cloud project"
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
```

Open http://127.0.0.1:5173.

**Simulation demo (2 minutes).** Click **Run scenario**, confirm, and watch the Overview. Debt rises in the morning peak, then falls to 0 when flexible jobs run in the green window. Open the Ledger and press **Verify now**. On the Experiments page, show the four-policy comparison.

**Live demo (3 minutes).** Click **Live** in the header, then **Start monitoring**.
1. On the **Telemetry** page, open Notepad or Chrome and watch it appear in the process table within a few seconds; close it and it disappears.
2. Show the grid panel: the reading, its timestamp and how fresh it is.
3. On the **Workloads** page, click **Add demo workloads**. Watch the emergency start immediately and the others wait or run. Open one to see measured energy and the reason for each decision.

If the grid is above the green threshold all day (common in India), Live mode will not show a green window. That is honest; use Simulation mode to show repayment.

---

## 12. Limitations (say these yourself)

- The cluster is 4 simulated workers on one laptop, not a real cloud.
- India Energy Atlas intensity is *modelled* by the provider; the free plans give the national figure only.
- Live energy is measured for the whole CPU package and shared by CPU time, which is an estimate of each job's share.
- Live amounts are tiny (milligrams) because a laptop task uses joules, not kilowatt-hours.
- Forecast errors are not modelled.
- The hash chain proves integrity only against a head hash kept somewhere safe.
- Throttling is done by the scheduler (capacity share), not by Windows CPU limits.

---

## 13. Likely viva questions, with short answers

1. **What is carbon debt?** The carbon emitted above a chosen threshold (350 g/kWh) when work had to run on dirty power: `energy × (intensity − 350)`.
2. **Does repaying debt remove emissions?** No. Credits count emissions avoided later by waiting for cleaner power. Past emissions stay in the "gross emissions" figure.
3. **Why can't any clean job earn credit?** Credit needs a baseline recorded *at the moment the controller deferred it*, so we know what it would have emitted. Running clean by luck earns nothing.
4. **How do you avoid missing deadlines?** A job is only moved to a slot where `start + runtime ≤ deadline`, with a 2-slot margin. Throttling follows the same rule. Emergencies are never delayed.
5. **What does the forecast add?** It plans ahead. Without it, jobs wait slot by slot and pile up at the last moment: 3.8 deadline misses per run versus 1.3 with the forecast.
6. **Is the energy real?** In Live mode, the CPU-package energy is measured by the Windows Energy Meter (Intel RAPL). Each job's share is estimated from its CPU time. In Simulation mode, energy is an estimate from declared power.
7. **Is CPU % the same as power?** No. We only use CPU time to *share out* measured energy.
8. **What if the API fails?** The dashboard shows "unavailable" with the reason, and live scheduling waits. We never insert a fake value.
9. **Is the ledger tamper-proof?** It is tamper-*evident*. Changing any entry breaks the SHA-256 chain. Someone with full database access could rewrite every hash, so the head hash should be saved somewhere else.
10. **Why two databases?** So simulated and real records can never be mixed up.
11. **Why poll the API every 20 minutes?** Free keys allow 100 calls per day, and the provider updates about every 15 minutes.
12. **Do you control Windows programs?** No. Ordinary programs are only watched. The scheduler controls only the small test workloads the app itself creates.
