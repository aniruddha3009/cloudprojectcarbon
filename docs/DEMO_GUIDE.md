# Complete demo guide: run it, explain it, demonstrate it

This guide is for the live demo and the viva. Part A tells you how to start the app. Part B explains the idea and the novelty in words you can say. Part C is a glossary of every term on the website. Part D walks through every page and says where each number comes from. Part E is a minute-by-minute demo script. Part F lists honest limitations and quick answers.

---

## Part A — How to run it

### A1. Start the app

Open **PowerShell** and run:

```powershell
cd "C:\Users\bomba\OneDrive\Desktop\cloud project"
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
```

Two windows open: the **backend** (FastAPI, port 8000) and the **frontend** (Vite, port 5173). Wait about 10 seconds, then open **http://127.0.0.1:5173** in Chrome or Edge.

- To check that the backend is alive, open http://127.0.0.1:8000/api/health. It should show `"status":"ok"`.
- To stop the app, close the two windows.
- If port 8000 or 5173 is already in use, an old copy is still running. Close it and start again.

### A2. API key (Live mode only)

The key is already in `.env` (`INDIA_ENERGY_ATLAS_API_KEY=...`). If you ever change the key, restart the backend. Never put the key in frontend code and never show it on screen.

### A3. Before the demo (5 minutes earlier)

1. Start the app. Make sure the header switch shows **Simulation**.
2. Go to **Experiments** and make sure the latest run shows **Clean-Energy Usage**. If not, open **New experiment** and click **Run experiment** (a few seconds).
3. Open **Live Mode**, switch to Live, click **Start monitoring**, and check that *Live Grid Data* shows a value, not *Unavailable*. Then stop monitoring and switch back to **Simulation**.
4. On the Overview, click **Reset Demo** so you start from 06:00 with an empty queue.
5. Keep **Notepad** closed; you will open it during the demo.

---

## Part B — What the project is, and why it is novel

### B1. The problem (say this first)

Electricity is cleaner at some times and dirtier at others. **Carbon intensity** is how many grams of CO₂ are emitted per kWh of electricity. In India it is usually 650–800 gCO₂e/kWh because most power comes from coal.

Cloud data centres run two kinds of work:

- **Urgent work** (for example a hospital model failing over) must run *now*, even when the grid is dirty.
- **Flexible work** (reports, backups, model training) can wait a few hours.

Existing "carbon-aware schedulers" delay flexible work to cleaner hours. But they **forget** the dirty urgent work. Nothing makes up for it.

### B2. Our idea in one sentence

> When urgent work has to run on dirty power, the extra carbon is written down as a **carbon debt**, and the scheduler is forced to **repay** it by moving flexible work into clean hours — with every gram recorded in a tamper-evident ledger.

### B3. The novelty — the six things to say

| # | Novel feature | What to say |
|---|---|---|
| 1 | **Carbon debt memory** | Ordinary schedulers make each decision on its own. Ours *remembers* past dirty emissions as a debt, and that debt changes future decisions. |
| 2 | **Priority inversion** | While debt is outstanding, a flexible job's right to run depends on carbon, not on its priority. A low-priority job that repays more debt runs *before* a high-priority job. |
| 3 | **Verified credits (counterfactual)** | A job earns credit only if we recorded, *at the moment we delayed it*, what it would have emitted if it had run immediately (the **baseline**). If it later runs cleaner, on time, the difference is the credit. Running clean by luck earns nothing. |
| 4 | **No banking** | Credits can only pay off debt that already exists. Clean work today cannot "pre-pay" tomorrow's emergency. The balance never goes below zero. |
| 5 | **Deadline-safe progressive throttling** | The more debt, the more non-urgent jobs are slowed (100% → 50% → 20% → paused) — but never emergencies, and never so much that a deadline is missed. |
| 6 | **Hash-chained audit ledger + carbon receipts** | Every debt and credit is linked by SHA-256 to the previous entry, so editing any record is detected. Each job gets a JSON carbon receipt. |

Plus: a **predictive planner** that uses the forecast to book the cleanest future slot that still meets every deadline, and **Live mode**, which uses real Indian grid data and measured laptop energy.

### B4. The key formulas (write these on the board if asked)

```
energy (kWh)     = power (W) × time (h) ÷ 1000
emissions (g)    = energy × intensity
debt (g)         = energy × max(0, intensity − 350)        ← only the part above the threshold
credit (g)       = max(0, full-speed energy × baseline − actual emissions)
credit applied   = min(credit, outstanding debt)            ← no banking
outstanding debt = total debt − credits applied             (never below 0)
```

**Worked example.** The emergency uses 1.5 kWh at 600 g/kWh → emissions 900 g, debt 1.5 × (600 − 350) = **375 g**. A flexible job of 1 kWh was due to run at 630 (its baseline) but waited and ran at 140 → credit 1 × 630 − 140 = **490 g**. 375 g is applied (debt becomes 0); the extra 115 g is *not banked*.

### B5. Credits do not erase carbon

Say this clearly: "A credit does **not** remove emissions that already happened. It records emissions we **avoided later** by waiting for cleaner power. That is why the website always shows gross emissions, debt and credits as separate numbers."

---

## Part C — Glossary: every term on the website

### Modes and data labels

| Term | Meaning |
|---|---|
| **Simulation mode** | Repeatable demonstration. Simulated grid curve, simulated 15-minute clock, estimated energy. Same input → same output every time. |
| **Live mode** | Real data: real Indian grid intensity from India Energy Atlas, real Windows processes, measured CPU energy, real clock with 30-second slots. |
| **SIMULATED** | The value comes from the simulator, not the real world. |
| **LIVE** | The value came from the real India Energy Atlas API. |
| **MEASURED** | Read from a real counter on this laptop. |
| **ESTIMATED** | Calculated from a model (for example declared power × time). |
| **PERSISTENCE** | No forecast available, so the latest real reading is assumed to continue. |
| **UNAVAILABLE** | No real reading exists; the app shows "—" instead of a made-up number. |
| **ESTIMATED_MODEL** | Job energy = declared power × time (Simulation mode). |
| **MEASURED_RAPL_ATTRIBUTED** | Job energy = measured CPU-package energy × (job's CPU time ÷ all busy CPU time) (Live mode). |
| **ESTIMATED_CPU_TIME** | Live fallback when the laptop has no energy meter. |

### Carbon terms

| Term | Meaning |
|---|---|
| **gCO₂e/kWh** | Grams of CO₂-equivalent per kilowatt-hour. The carbon intensity of electricity. |
| **Grid intensity** | The current carbon intensity of the electricity grid. |
| **Debt threshold** (default 350) | Running above this intensity creates debt. |
| **Green threshold** (default 200) | At or below this, the grid counts as clean. |
| **Green window** | A period when intensity ≤ green threshold. Shaded on charts. |
| **Gross emissions** | All emissions, energy × intensity. Never reduced by credits. |
| **Carbon debt** | Emissions above the debt threshold: energy × (intensity − 350). |
| **Effective debt** | Debt booked in the ledger **plus** debt still accruing from jobs running now. The controller acts on this. |
| **Balance / Outstanding** | Total debt − credits applied. Never negative. |
| **Baseline intensity** | The intensity the job *would have* run at if started when it was deferred. Recorded at that moment. |
| **Credit earned** | full-speed energy × baseline − actual emissions (if positive). |
| **Credit applied** | The part of the credit that actually reduced debt (capped at the balance). |
| **Surplus not banked** | Credit earned beyond the balance. Recorded but thrown away. |
| **Net balance impact** | Debt this job caused − credit it applied. |

### Job terms

| Term | Meaning |
|---|---|
| **Emergency** | Runs immediately, never delayed, never throttled. One worker is always reserved for it. |
| **Normal** | Can wait, but has a firm deadline. |
| **Background** | Most flexible; slowed first when debt is high. |
| **Priority** | 1 = highest, 5 = lowest. Used when there is no debt. During priority inversion, repayment value matters more. |
| **Runtime** | How long the job needs at full speed. |
| **Deadline** | The job must have finished by this time. |
| **Capacity** | Share of a worker the job gets: 100%, 50%, 20% or 0% (paused). At 50% it progresses half as fast. |
| **Workers** (default 4) | How many jobs can run at the same time. |
| **Emergency reserve** (default 1) | Workers flexible jobs may never use. |
| **Max wait** | Optional anti-starvation limit: start after waiting this long. |

### Job states

| State | Meaning |
|---|---|
| **Pending** | Not arrived yet (arrival time is in the future). |
| **Queued** | Arrived, waiting for the scheduler. |
| **Deferred** | The controller decided to delay it (to a cleaner slot). A baseline is recorded. |
| **Running** | Executing. |
| **Paused** | Throttled to 0% because debt is critical; will resume in time for its deadline. |
| **Completed / Failed / Cancelled** | Finished. A carbon receipt is issued. |

### Controller terms

| Term | Meaning |
|---|---|
| **Policy** | The scheduling rule: FIFO, Threshold, Debt controller (reactive), Predictive controller. |
| **FIFO** | First in, first out. Ignores carbon. The baseline for comparison. |
| **Threshold** | Waits while intensity is above 350, unless the deadline forces it. |
| **Debt controller (reactive)** | Threshold + debt: while in debt, flexible work runs only in green slots; throttling by debt band. No forecast. |
| **Predictive controller** | Debt controller + forecast planner that books the cleanest feasible future window. |
| **Priority inversion** | While debt > 0, jobs are ordered by repayment value, not priority. |
| **Repayment value** | energy × (baseline − current intensity): how much debt running now would repay. |
| **Debt bands** | NORMAL (0) → REPAYING (> 0) → THROTTLE_SOFT (≥ 100 g) → THROTTLE_HARD (≥ 400 g) → CRITICAL (≥ 800 g). |
| **Throttling** | Reducing a job's capacity by debt band. A scheduler share, not Windows CPU limiting. |
| **Proactive throttling** | Moving one band higher early when the forecast says the debt cannot be repaid in time. |
| **Deadline-forced** | The job had to start now or it would miss its deadline. Deadlines beat carbon. |
| **Safety margin** | Jobs are planned to finish 2 slots before the deadline. |
| **Repair pass** | If the plan leaves a job with no feasible window, earlier jobs are pinned and the plan is rebuilt. |
| **Projection** | The planner's forecast of future debt: projected peak and balance at the horizon. |
| **Horizon** | The end of the planning window. |
| **Advisory plan** | Shown for FIFO/Threshold/Reactive: what the planner *would* do, but it is not in control. |
| **Slot** | One scheduling step: 15 minutes in Simulation, 30 seconds in Live. |

### Carbon debt history terms (technical)

| Term | Meaning |
|---|---|
| **DEBT_INCURRED** | Debt booked when a job ends (sum of its per-slot debt). |
| **DEFERRAL_RECORDED** | The controller delayed a job; its baseline is stored here, *before* the outcome is known. |
| **CREDIT_VERIFIED** | A credit passed all checks and was applied. |
| **CREDIT_DENIED** | A job did not qualify (for example it missed its deadline or was run manually); the reasons are stored. |
| **DEBT_CLEARED** | The balance reached zero; priority inversion ends. |
| **Hash** | SHA-256 of the entry's fields plus the previous hash. |
| **Previous hash** | Links this entry to the one before it. Entry 1 uses 64 zeros. |
| **Chain head** | The hash of the newest entry. Represents the whole ledger. |
| **Checkpoint** | A saved copy of the head hash, kept elsewhere, to detect rewriting. |
| **Idempotency key** | A unique key (`DEBT:J-001`, `CREDIT:J-001`) that stops the same event being booked twice. |
| **Verified / Tampered** | Result of re-checking every hash and balance. |

### Experiment terms

| Term | Meaning |
|---|---|
| **Seed** | Number that fixes the random workload and grid noise. Same seed → identical inputs. |
| **Trace** | The generated list of jobs for one seed (default 36 jobs). |
| **Mean ± std** | Average across seeds, and the standard deviation (spread). |
| **Reference policy** | The policy others are compared against (FIFO). Percentages are relative to it. |
| **Sweep** | Re-run with one setting changed over several values (for example green threshold 150, 200, 250). |
| **Profile** | Shape of the simulated grid: *solar midday* (clean at noon), *windy night* (clean at night), *dirty flat* (never clean). |

### Live terms

| Term | Meaning |
|---|---|
| **India Energy Atlas** | The provider of the real Indian grid intensity (api.energymap.in). |
| **All-India / national** | One number for the whole country. The free plan gives only this. |
| **Dominant fuel** | The fuel with the largest generation in that hour (usually coal). |
| **Freshness** | How old the latest reading is. The provider publishes hourly, so up to ~1 h is normal. |
| **Stale** | The reading is older than 3 hours. |
| **CPU package power** | Watts used by the processor chip, from the Windows Energy Meter (Intel RAPL). |
| **RAPL** | Running Average Power Limit: Intel's built-in energy counter. |
| **PID** | Process ID: Windows' number for a running program. |
| **Managed workload** | A small, bounded CPU task started by *this app*. The only things the scheduler controls. |

---

## Part D — Page by page: what each value is and where it comes from

The frontend never calculates carbon. It only displays what the backend returns. Navigation: **Overview · Process Queue · Scheduler · Experiments · History · Live Mode**.

### D0. The frame (on every page)

| Item | What it shows | Source |
|---|---|---|
| **Simulation / Live** switch | The active mode. Each mode has its own database. | `PUT /api/mode` |
| Clock | Simulation: simulated time (UTC). Live: your local time. | `/api/state` |
| Intensity (`xxx gCO₂e/kWh`) | Green = clean (≤ 200), amber = moderate, red = above 350. | Simulated curve, or the latest India Energy Atlas reading |
| **Step 15 min / Play** (Simulation) | Advance one 15-minute step, or keep stepping automatically. | `POST /api/sim/advance`, `/api/sim/autoplay` |
| **Start / Stop monitoring** (Live) | Starts the process monitor, the grid feed and the 30-second live steps. | `POST /api/live/monitoring` |
| Sidebar card | Data sources: *Simulated* / *Estimated Energy* in Simulation; *Live Grid Data*, *Estimated Energy (measured CPU power)*, *Live Process Monitoring* in Live. | `/api/state` |

### D1. Overview (Simulation mode) — the demo screen

**Electricity right now**
- Big number: current simulated intensity, and a plain label: *Clean electricity* (≤ 200), *Moderate*, or *Carbon-intensive* (> 350).
- Line below: "Simulated · normal daily pattern" or "set manually until 08:15, then the normal daily pattern".
- **Switch to Green Energy** = 120 gCO₂e/kWh, **Switch to Coal-Heavy Energy** = 650, **Set carbon intensity** = any value 0–2000. **For**: 1 h, 2 h (default), 4 h, or the rest of the run. **Back to normal pattern** removes the manual setting from now on.
- Source: `POST /api/sim/grid`. The setting starts at the current step. Steps already played keep the value they had, so history never changes. The scheduler's forecast also uses it — that is why, after "coal-heavy for 2 hours", it can still expect the solar dip at noon.

**Demo controls**
- **Load Sample Processes** (`POST /api/demo/samples`): resets the simulation to 06:00 and adds four processes that arrive now:

| Process | Type | Runs | Deadline | What it shows |
|---|---|---|---|---|
| Hospital alert system | Urgent, priority 1 | 30 min, 1500 W | 60 min | Runs immediately, even on coal |
| Payroll report | Normal, priority 2 | 30 min, 800 W | 45 min | Deadline too close to wait |
| Nightly data backup | Normal, priority 3 | 60 min, 1000 W | 10 h | Flexible: postponed to a cleaner time |
| AI model training | Flexible, priority 4 | 60 min, 1200 W | 12 h | Flexible: postponed to a cleaner time |

- **Add Process**: name, how flexible it is (Urgent / Normal / Flexible), priority, power, run time, deadline. It shows estimated energy = power × time. Optional extras (application name, later arrival, maximum wait, deliberate failure) are under *More options*.
- **Step 15 min**, **Play/Pause**, **Reset Demo** (clears processes and history, clock to 06:00, grid back to normal).
- "Or play the full automatic scenario" runs the original 8-process, 06:00–16:00 story by itself.

**Process queue** — the centre of the demo

| Column | Meaning |
|---|---|
| Process | Name, type badge, and "+X g debt" / "repaid X g" once it has run |
| Priority | 1 = highest |
| Status | Running, Waiting, Scheduled for later, Paused, Completed, Failed, Cancelled |
| Scheduled time | The booked start time (if scheduled for later), or when it started / finished |
| Reason | One sentence, generated by the backend from the scheduler's **actual last decision** (`plain_reason` in `/api/jobs`) |

The sentences you will see, and the decision each comes from:

| Sentence | Scheduler decision |
|---|---|
| Running now because this is an emergency. | `EMERGENCY_START` |
| Running now because its deadline is approaching. | `START_FORCED` (no time left to wait) |
| Running now because no cleaner time is expected before its deadline. | `START` above the threshold, forecast has nothing cleaner in time |
| Running now because electricity is clean. / …below the carbon limit. | `START` at ≤ 200 / ≤ 350 |
| Running now because electricity is clean; this work repays carbon debt. | `REPAYMENT_START` |
| Scheduled for 12:00 because cleaner electricity is expected. | `DEFER` by the predictive controller (books a later time) |
| Waiting because electricity is carbon-intensive and this process can wait. | `DEFER` by the threshold / debt controller (re-checks every step) |
| Running at 50% speed because carbon debt is high… / Paused because carbon debt is high… | `THROTTLE` / `PAUSE` |
| Running now: this policy ignores carbon… | FIFO policy |
| Finished before its deadline. | Completed on time |

**Why this decision?** (click a row): status, the sentence above, type, priority, the grid intensity at the moment of that decision, deadline and time left, the scheduler's exact technical reason, and the process's energy, emissions, debt added and debt repaid. *Technical details* inside it holds the full decision list, status history, per-step energy table, debt records and the JSON carbon receipt.

**Carbon debt**
- **Carbon Debt Added** = all debt recorded + debt still accumulating from running processes.
- **Carbon Debt Repaid** = carbon avoided by postponed processes that later ran cleaner (only up to the debt that existed).
- **Carbon Debt Remaining** = Added − Repaid (never below 0).
- The formula box: `Carbon debt = Energy used × max(0, Grid intensity − 350)`, with the 1 kWh × (600 − 350) = 250 g example, and the sentence that repaying does **not** erase emissions.
- Small chart: debt over the simulated day. Source: `/api/state` (`ledger` fields) and `/api/timeline`.

**Electricity over time** — the simulated curve for the day: solid = played, dashed = forecast, green band = clean periods, red dashed line = 350 threshold. Source: `/api/carbon/curve`.

**How the scheduler decides** (collapsed) — the five rules in plain English.

### D1b. Overview in Live mode
Live Grid Data card, the Carbon debt panel (tiny amounts, shown with 3 decimals), the process queue of this app's test processes, and the "can / cannot control" box.

### D2. Process Queue
The same queue table, plus search, a status filter, **Run now** (start at the next step regardless of carbon — it then cannot earn a repayment) and **Cancel** for each process, and the **Add Process**, **Load Sample Processes** and **Reset Demo** buttons. In Live mode the buttons add or clear the four small live test processes.

### D3. Scheduler
- Four cards: **Carbon debt threshold** (350), **Clean-electricity level** (200), **Carbon debt now** (with a plain status such as "Debt is building: flexible work slowed to 50%"), **Grid now**.
- **The rules**: five plain rules, and the active policy.
- **Planned start times**: each waiting flexible process with its booked time, "clean period" / "deadline protection" tags, intensity now → in that window, how much debt it could repay, and the planner's reason.
- **Settings**: policy and the two thresholds; *Advanced settings* holds debt slow-down levels, workers, emergency reserve, static power, proactive slow-down, and the simulated grid's profile/seed/noise.
- **Technical details**: debt forecast chart, postponed processes with their saved baselines, running processes, the slow-down table, and the last 80 decisions.

### D4. Experiments (always simulated)
- **Do the carbon-aware policies help?** — one table, four columns, best value per column in green:

| Policy | Total Carbon Emissions | Carbon Debt Remaining | Clean-Energy Usage | Deadline Misses / run |
|---|---|---|---|---|
| FIFO | 20.64 kg | 5,385 g | 16.6% | 0.2 |
| Threshold | 17.59 kg | 469 g | 20.3% | 1.3 |
| Debt controller | 16.88 kg | 72 g | 32.5% | 3.8 |
| Predictive controller | 17.2 kg | 248 g | 29.0% | 1.3 |

- **Clean-Energy Usage** = energy used while the grid was ≤ 200 ÷ all energy used (`clean_energy_pct`, computed from every step of every run).
- The conclusion sentence is built only from these numbers. For this run: *"Compared with FIFO, the predictive controller left less carbon debt, used clean electricity more often and emitted less carbon. It missed 1.1 more deadlines per run (1.3 vs 0.2), because it waits for cleaner periods."*
- Say it plainly: no policy wins everything. The debt controller is best on carbon but misses the most deadlines; the forecast brings misses back down to 1.3.
- **Advanced details**: every metric with ± standard deviation, a bar chart per metric, debt over time per policy, the optional parameter sweep, and the method.
- **New experiment**: seeds, policies, numbers of each process type, grid profile, thresholds, optional sweep. **Saved runs**: earlier runs.

### D5. History (carbon debt history)
- Three cards: **Carbon Debt Added**, **Carbon Debt Repaid**, **Carbon Debt Remaining** (recorded values; debt is recorded when each process finishes).
- **Records**: time, what happened (*Debt added*, *Process postponed (baseline saved)*, *Debt repaid*, *Ran cleaner, but no debt was left to repay*, *No repayment (not eligible)*, *Debt fully repaid*), process, change, debt before, debt after. Click a record for its calculation. **Export CSV**.
- **By application**: emissions, debt added, debt repaid, postponements, misses, average delay per application.
- **Technical details**: SHA-256 hash-chain verification, checkpoint, and the tamper demonstration (changes a copy only).

### D6. Live Mode
- **Live Grid Data**: real all-India intensity, *Clean electricity* / *Moderate* / *Carbon-intensive*, when it was updated, and the source (India Energy Atlas). If there is no reading it says **Unavailable** with the reason.
- **Live Process Monitoring**: CPU % and memory % of the laptop, number of programs detected, CPU power in watts (measured by the Windows Energy Meter).
- **What the scheduler can and cannot control**.
- **Detected processes**: the top 25 programs by CPU (search shows up to 100). Watched only.
- **Technical details**: grid feed status, next fetch, API calls today, *Fetch now*, energy-meter explanation (each live test process gets an **estimated** share of measured CPU energy by CPU time), the managed test processes, measurement notes, admin token.

---

## Part E — The demo script (about 10 minutes)

| Time | Where | Do | Say |
|---|---|---|---|
| 0:00–1:00 | Overview | Point at the title and the three panels | "Urgent computing sometimes has to run on coal-heavy electricity. We record the extra carbon as carbon debt, and the scheduler repays it by moving flexible work to cleaner periods." |
| 1:00–1:30 | Overview | **Load Sample Processes** | "Four processes arrive at 06:00: an urgent hospital alert, a payroll report due in 45 minutes, and two flexible jobs with all day to finish." |
| 1:30–3:00 | Overview | **Switch to Coal-Heavy Energy**, then **Step 15 min** | "The grid is now 650 — carbon-intensive. The hospital alert runs anyway: it is an emergency. The payroll report runs because its deadline is too close. The backup and the training are scheduled for 12:00, because the forecast expects cleaner electricity then." Point at Carbon Debt Added rising. |
| 3:00–3:30 | Overview | Click **Why this decision?** on Nightly data backup | "Its status, the grid at the moment of the decision, its deadline, and the scheduler's exact reason." |
| 3:30–5:00 | Overview | **Switch to Green Energy**, then **Step** 4 times | "The grid is 120 — clean. The flexible jobs start now: running on clean power repays the debt. Added 173 g, repaid 173 g, remaining 0. The formula is here: energy × (intensity − 350). Repaying does not erase the carbon already emitted; it records carbon we avoided by waiting." |
| 5:00–6:00 | Scheduler | Cards and rules | "Two thresholds: 350 for debt, 200 for clean. Five rules. Urgent work and deadlines always win over carbon." |
| 6:00–7:30 | Experiments | Results table and conclusion | "The same 360 simulated processes under four policies. Predictive leaves 95% less debt than FIFO and uses clean electricity 29% of the time instead of 17%, but it misses about one more deadline per run because it waits. No policy is best at everything." |
| 7:30–8:00 | History | Records, then Technical details → tamper demo | "Every addition and repayment is recorded, and changing an old record is detected." |
| 8:00–10:00 | Live Mode | Switch to Live, **Start monitoring**; open Notepad and search it | "This is the real Indian grid right now — around 700, carbon-intensive — from India Energy Atlas, with its update time. These are the real programs on this laptop. The scheduler only controls its own test processes; it never touches other programs." |

**Afterwards:** Stop monitoring and switch back to Simulation.

### If something goes wrong during the demo

| Problem | What to do |
|---|---|
| "Backend unreachable" | The backend window was closed. Run `start-dev.ps1` again. |
| Live grid says *Unavailable* | Say: "The app shows the provider's real error instead of inventing a value." Continue with Simulation. |
| Queue looks messy | **Load Sample Processes** again (it resets first). |
| Experiments show no Clean-Energy Usage | That run is older; click **New experiment → Run experiment** (a few seconds). |
| Live processes stay "Waiting" | Monitoring is off, or there is no grid reading yet. |

---

## Part F — Honest limitations and quick answers

**Say these yourself before you are asked:**

- The "cloud" is a 4-worker simulated cluster on one laptop. The app is containerised and ready for a cloud VM, but it was not deployed (Docker was not installed on the development machine).
- Simulation energy is an estimate from declared power. Live energy is measured for the whole CPU package and **shared** by CPU time — the share is an estimate.
- India Energy Atlas intensity is **modelled** by the provider (about ±3% nationally), hourly, and the free plan gives only the all-India figure.
- Forecast errors are not modelled.
- The hash chain proves integrity only against a head hash stored elsewhere.
- Throttling is a scheduler-level capacity share, not Windows CPU limiting.

**Quick answers**

| Question | Answer |
|---|---|
| Is this just a dashboard? | No. The backend scheduler makes every decision, runs the jobs and writes everything to the database. The frontend only reads and displays. |
| Why 350 and 200? | Policy settings, editable on the Controller page; the sweep shows their effect. |
| Do credits erase emissions? | No. They count emissions avoided later. Gross emissions are never reduced. |
| Why can't any clean job earn credit? | Credit needs a baseline recorded when the controller deferred it. Luck earns nothing. |
| How are deadlines protected? | Jobs are only moved where start + runtime ≤ deadline with a 2-slot margin; throttling follows the same rule; emergencies are never delayed. |
| Why two databases? | So simulated and real records can never mix. |
| What happens if the API fails? | The page shows "unavailable" with the reason, live jobs wait, nothing is invented. |
| Why poll every 20 minutes? | Free keys allow 100 calls a day and the data is hourly. |
| How do you know it works? | 82 automated tests, deterministic replays, ledger verification, and the scenario strip reads saved records. |
