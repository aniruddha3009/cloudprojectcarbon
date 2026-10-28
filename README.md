# Carbon Debt Computing

Individual project for **Challenge 9: Carbon Debt Computing**.

When urgent computing must run on carbon-heavy electricity, the extra carbon is booked as **debt** in a hash-chained ledger. While debt is outstanding, flexible work is moved into **green** (low-carbon) periods, non-critical work is throttled, and no job misses its deadline because of it. Every repayment **credit** is checked against a baseline recorded in advance.

The app has exactly two modes:

| Simulation mode | Live mode |
|---|---|
| Repeatable demonstration with a simulated grid (labelled SIMULATED). Works offline, no API key. | Real data: India Energy Atlas grid intensity, this laptop's Windows processes, CPU/memory, and **measured** CPU-package energy (Windows Energy Meter / Intel RAPL). |

**New to the code?** Read [docs/LEARNING_GUIDE.md](docs/LEARNING_GUIDE.md) first. **Preparing the demo?** Read [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md): every page, every value and a 10-minute script.

---

## Start it (Windows 11)

You need Python 3.11+ and Node.js 20+.

```powershell
cd "C:\Users\bomba\OneDrive\Desktop\cloud project"
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
```

This opens two PowerShell windows (backend and frontend) and the dashboard at **http://127.0.0.1:5173**. The API docs are at http://127.0.0.1:8000/docs. To stop, close the two windows.

## Live mode: add your API key (only needed for the grid reading)

1. Create a free account at https://www.energymap.in. Verified Indian academic emails get the free **Student** plan; **Sandbox** is free for anyone.
2. Go to **Settings → API Keys** (https://www.energymap.in/settings#api-keys), click **Generate key**, and copy it. It looks like `iea_live_...` and is shown once.
3. Open the file **`.env` in the project folder** (next to this README) and paste the key after the `=` (no quotes):
   ```
   INDIA_ENERGY_ATLAS_API_KEY=iea_live_your_key_here
   ```
4. **Restart the backend**: close its window and run `start-dev.ps1` again.
5. Check it: open **Live Mode**, switch to Live, and click **Start monitoring**. The *Live Grid Data* card should show a value with its update time instead of *Unavailable*.

| You see | Meaning | Fix |
|---|---|---|
| API key missing | `INDIA_ENERGY_ATLAS_API_KEY` is empty | Paste the key in `.env`, restart the backend |
| HTTP 401 invalid_api_key | Wrong, revoked or expired key, or extra spaces/quotes | Copy the key again or generate a new one |
| HTTP 402 feature_not_in_plan | State-level data is not in your plan | Leave `INDIA_ENERGY_ATLAS_STATE` empty (all-India figure) |
| HTTP 429 / daily budget | Free keys allow 100 calls per day | Wait; the app polls only every 20 min |
| unreachable | No internet | Reconnect; Simulation mode works offline |

`.env` is ignored by Git. Never put the key in frontend code or commit it. `.env.example` contains placeholders only.

## Demonstration

Navigation: **Overview · Process Queue · Scheduler · Experiments · History · Live Mode**.

**Simulation (about 4 minutes, all on the Overview page)**
1. **Load Sample Processes**: four processes arrive at 06:00 (one urgent, one with a close deadline, two flexible).
2. **Switch to Coal-Heavy Energy** (650 gCO₂e/kWh for the next 2 h), then **Step 15 min**. The process queue shows *Running now because this is an emergency.*, the payroll report running because no cleaner time is expected before its deadline, and the flexible ones *Scheduled for 12:00 because cleaner electricity is expected.* Carbon debt starts to build.
3. **Switch to Green Energy** (120), then **Step** a few times. The flexible processes run (*electricity is clean; this work repays carbon debt*). **Carbon Debt Added / Repaid / Remaining** ends at 173 g / 173 g / 0 g.
4. Click any row (**Why this decision?**) for the state, grid intensity, deadline and the scheduler's exact reason.
5. **Experiments → New experiment → Run** compares the four policies on Total Carbon Emissions, Carbon Debt Remaining, Clean-Energy Usage and Deadline Misses.

The 10-hour automatic scenario is still available ("Or play the full automatic scenario"). Hash-chain verification and the tamper demonstration are under **History → Technical details**.

**Live (about 2 minutes)**
1. Open **Live Mode**, switch to Live, click **Start monitoring**.
2. *Live Grid Data* shows the real all-India intensity, whether it is clean or carbon-intensive, and when it was updated. *Live Process Monitoring* shows CPU, memory and the detected programs; open Notepad and search for it.
3. **Process Queue → Load Sample Processes** adds four small CPU tasks run by this app. Only these are controlled; other Windows programs are only watched.
4. The Indian grid is rarely below 200 gCO₂e/kWh, so live debt is usually not repaid. That is the honest result; use Simulation to show repayment.

## Tests

```powershell
powershell -ExecutionPolicy Bypass -File .\run-checks.ps1
# or
cd backend;  .\.venv\Scripts\python -m pytest -q      # 82 tests
cd frontend; npm run build                           # type-check + production build
```

## Results (simulation, 10 seeds × 36 jobs)

| Policy | Gross emissions | Debt incurred | Final debt | Clean-energy usage | Deadline misses / run |
|---|---|---|---|---|---|
| FIFO (carbon-unaware) | 20,637 g | 5,385 g | 5,385 g | 16.6% | 0.2 |
| Threshold deferral | 17,588 g (−14.8%) | 2,965 g | 469 g | 20.3% | 1.3 |
| Debt controller, no forecast | 16,880 g (−18.2%) | 3,160 g | 72 g | 32.5% | 3.8 |
| **Predictive debt controller** | 17,197 g (−16.7%) | **2,880 g (−46.5%)** | 248 g | 29.0% | 1.3 |

Clean-energy usage = share of all energy used while the grid was at or below the green threshold (200 gCO₂e/kWh).

The trade-off is delay: flexible jobs finish hours later. Regenerate the results with `backend\.venv\Scripts\python tools\generate_results.py`.

## Project structure

```
backend/app/core/        engine, policies, planner, accounting, ledger, hash chain (pure, deterministic)
backend/app/services/    simulation.py, live.py, india_energy_atlas.py, system_monitor.py, modes.py, experiments.py
backend/app/api/         REST routes
backend/tests/           pytest suite
frontend/src/            React + TypeScript dashboard (six pages)
docs/                    learning guide, architecture, algorithms, measurement, experiments, demo, viva, poster, proposal
tools/                   results generator, Word proposal builder
```

## Documentation

[LEARNING_GUIDE](docs/LEARNING_GUIDE.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) · [ALGORITHMS](docs/ALGORITHMS.md) · [MEASUREMENT_METHODOLOGY](docs/MEASUREMENT_METHODOLOGY.md) · [EXPERIMENTS](docs/EXPERIMENTS.md) · [DEMO_SCRIPT](docs/DEMO_SCRIPT.md) · [VIVA_PREPARATION](docs/VIVA_PREPARATION.md) · [CLOUD_DEPLOYMENT](docs/CLOUD_DEPLOYMENT.md) · [POSTER](docs/POSTER.md) · [PROPOSAL_CONTENT](docs/PROPOSAL_CONTENT.md)

## Troubleshooting

| Problem | Fix |
|---|---|
| Port 8000 or 5173 already in use | Close the old windows; `Get-NetTCPConnection -LocalPort 8000` shows the process |
| "Backend unreachable" | Start the backend; check http://127.0.0.1:8000/api/health |
| `python` / `npm` not found | Install Python 3.11+ (tick *Add to PATH*) and Node 20, then open a new terminal |
| Script blocked | Use `powershell -ExecutionPolicy Bypass -File .\start-dev.ps1` |
| Messy simulation data | Overview → Reset Demo (or Load Sample Processes, which resets first) |

## Limitations

The cluster is simulated on one laptop. India Energy Atlas intensity is modelled by the provider (all-India on free plans). Live energy is measured for the whole CPU package and shared out by CPU time. Forecast error is not modelled. Credits record avoided future emissions and never erase past ones. The hash chain is trustworthy only against an externally kept head hash.
