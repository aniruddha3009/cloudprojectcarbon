# Algorithms

All algorithms live in `backend/app/core/` and are pure and deterministic: no database, no network and no random calls at decision time. The same code drives the live dashboard and the experiments.

## 1. Time model

- The day is split into **15-minute slots** (96 per day). The simulation horizon is 3 days (slots 0–287).
- `Engine.step()` processes one slot in this fixed order: arrivals → operator actions → **policy decision** → **execution** → settlement → deadline checks → timeline snapshot.
- A job's deadline `D` is a slot index, and the job must have *finished* by the start of slot `D`.

## 2. Carbon accounting

Units: energy in kWh, intensity in gCO₂e/kWh, carbon mass in gCO₂e, power in W. All accounting uses Python `Decimal`, quantised **per slot** with banker's rounding (energy 9 dp of kWh, grams 6 dp, intensity 2 dp) and then summed. Results are therefore bit-identical across runs.

For a job running in slot *t* at capacity *c* (see §6):

```
P(c)            = P_declared × (s + (1 − s) × c)        s = static power share (0.30)
energy_t        = P(c) × minutes_used / 60 / 1000                        [kWh]
emissions_t     = energy_t × I_t                                        [g]
debt_t          = energy_t × max(0, I_t − I_threshold)                  [g]
```

A job's **gross emissions** and **debt** are the sums over its slots. Debt is *policy-defined excess carbon*: the part of the emissions caused by running above the threshold `I_threshold` (default 350 gCO₂e/kWh). It is not the total footprint.

Debt is **booked in the ledger when the job ends** (completed, failed or cancelled), as one `DEBT_INCURRED` event. While the job runs, its debt is **accruing**. The controller always acts on the **effective debt**:

```
effective_debt = ledger_balance + Σ accrued debt of running jobs
```

## 3. Verified savings credits

When the controller **deliberately defers** a job that could have started now (a worker was free), the first deferral appends a hash-chained `DEFERRAL_RECORDED` event. It holds the counterfactual **baseline**: the forecast mean intensity of the window the job would have occupied had it started immediately.

When the job ends, `evaluate_credit` checks **all** of the following:

| Check | Why |
|---|---|
| deferred by the controller and a deferral event exists | an operator hold or a capacity wait is not a carbon decision |
| baseline recorded | the counterfactual must be fixed *before* the outcome is known |
| completed successfully | failed or cancelled work avoided nothing |
| finished by its deadline | late work is not a legitimate shift |
| not already credited (idempotency key `CREDIT:<job>`) | no duplicates |
| no operator override (manual "run now") | the controller no longer chose the window |
| avoided emissions > 0 | running "green" by luck earns nothing |

```
credit_earned  = max(0, E_full × I_baseline − actual_emissions)
credit_applied = min(credit_earned, outstanding_balance)
```

`E_full` is the job's full-speed energy. Comparing *total emissions* rather than intensities charges any extra energy caused by throttling against the credit. For an un-throttled job this reduces to `E × (I_baseline − I_actual)`.

**Balance policy.** Credits beyond the outstanding balance are recorded as `surplus_not_banked_g` but never applied. The balance cannot go below zero (`LedgerBook` raises an error if asked to), and past green work cannot pre-pay future emergencies. When a credit brings the balance from > 0 to 0, a `DEBT_CLEARED` event is appended and **priority inversion ends**. Ineligible jobs get a `CREDIT_DENIED` event recording the reasons, which makes the denial auditable too.

> Credits are an **accounting of avoided future emissions**. They do not and cannot remove emissions that already happened. The dashboard therefore shows debt, credits and gross emissions separately.

## 4. Policies

All four policies share emergency handling, capacity rules, deadline checks and accounting. Only the decision step differs.

**Emergency precedence (all policies).** Emergency jobs start at 100% capacity in the slot they arrive, regardless of intensity. `emergency_reserve` workers (default 1 of 4) are never used by flexible work, so an emergency always finds a free worker unless several emergencies coincide. The cluster is non-preemptive.

| Policy | Flexible-job rule |
|---|---|
| `fifo` | start in priority/arrival order whenever a worker is free |
| `threshold` | run if `I_t ≤ I_threshold`; otherwise defer one slot if still feasible, else deadline-forced start |
| `debt_reactive` | **no debt:** threshold rule. **Debt > 0 (priority inversion):** start only in green slots (`I_t ≤ G`); otherwise defer one slot if still feasible, else deadline-forced. Waiting jobs are ranked by **repayment value** `E × (baseline − I_t)` instead of nominal priority. Progressive throttling. |
| `debt_predictive` | the predictive planner (§5) + progressive throttling + proactive throttling |

## 5. Predictive planner (the full controller)

Every slot, `planner.build_plan` builds a capacity-aware reservation plan over the forecast horizon (≥ 24 h, and up to the latest deadline):

1. **Free-capacity table.** For each future slot: `workers − reserve − capacity of running flexible jobs`, each assumed to keep its current capacity until it finishes (paused jobs are assumed to resume at full speed).
2. **Order.** Waiting jobs reserve capacity **earliest-deadline-first** (EDF), which protects feasibility. Ties are broken by repayment value while debt is outstanding, otherwise by priority.
3. **Candidate windows.** Every start slot `s` with `s + runtime ≤ deadline` and free capacity in every slot of the run. A safety margin of up to 2 slots before the deadline is kept when the slack allows.
4. **Choice.** Score each window by forecast mean intensity. **While debt > 0, only fully green windows are allowed** if any exist (strict green-slot repayment). If none fits before the deadline, use the least-carbon feasible window (deadline protection beats green-only). Choose the earliest window within 10 gCO₂e/kWh of the best.
5. **No pointless delay.** Without debt, a job is delayed only if the expected saving `E × (I_now − I_window)` is at least `min_deferral_savings_g` (5 g).
6. **Repair pass.** If any job ends up with no feasible window, the earlier-deadline jobs that were being delayed are pinned to their earliest feasible start and the plan is rebuilt (≤ 3 passes). Greedy carbon placement must not starve a later job of capacity.
7. **Debt projection.** Walk the plan forward. Debt arrives when a run ends above the threshold; expected credits arrive when deferred jobs finish (capped at the balance). The result gives the **projected peak** and the **balance at the horizon**.
8. **Proactive throttling.** If the projection shows debt still outstanding at the horizon, or a peak above the critical band, the throttle band is raised one level *before* the debt actually gets there.

The plan's reason text is written straight to the decision log, for example:

> *Deferred until 12:00 because projected intensity falls from 633 to 142 gCO₂e/kWh (est. saving 491 g), the deadline 16:00 remains feasible (latest start 15:00), and 1,029 g debt is outstanding, so flexible work is restricted to green slots.*

**Complexity** per slot: `O(J · W · R)` for J waiting jobs, W candidate start slots and R slots per run, times at most 3 repair passes. Window averages use prefix sums (O(1)). The measured mean decision time is ≈ 0.8 ms per slot with 36 jobs (`decision_overhead_us`), against 0.01 ms for FIFO.

**Forecast uncertainty is not modelled.** In simulation the forecast equals the realised curve. In Live mode the India Energy Atlas forecast is used when the plan returns one, otherwise the latest reading is held (PERSISTENCE). This is stated in the UI.

## 6. Progressive, deadline-safe throttling

Throttling is a **scheduler-level capacity share** `c ∈ {1, 0.5, 0.2, 0 (paused)}`. A job at `c` progresses `15·c` minutes of work per slot and occupies `c` of a worker, so the freed share can be used by other jobs. It is **not** OS-level CPU throttling.

| Debt band (effective debt) | State | Normal jobs | Background jobs |
|---|---|---|---|
| 0 | NORMAL | 100% | 100% |
| 0 < D < soft (100 g) | REPAYING | 100% | 100% |
| soft ≤ D < hard (400 g) | THROTTLE_SOFT | 100% | 50% |
| hard ≤ D < critical (800 g) | THROTTLE_HARD | 50% | 20% |
| ≥ critical | CRITICAL | 20% | paused |

Rules:
- It applies only **outside green windows**. In a green slot every job runs at full speed.
- **Emergency jobs are never throttled.**
- **Deadline safety.** `min_feasible_capacity` picks the smallest level at or above the band's level that still finishes **2 slots before** the deadline. A pause is allowed only if the job can still finish at full speed when it resumes next slot. When nothing is feasible, the job runs at 100%.
- Raising capacity again needs free capacity. A restore that cannot get it is logged as *capacity-limited*.

**Energy penalty.** With static share `s = 0.3`, half speed draws 65% of the power for twice as long, so the same work costs **1.3×** the energy. Throttling therefore saves carbon only when it moves work into cleaner slots. In the experiments, the predictive controller uses 3% more energy than FIFO (51.3 vs 49.8 kWh) and still emits 16.7% less.

## 7. Hash-chained ledger

Each ledger record contains: `seq, event_id, event_type, job_id, sim_time, recorded_at, energy_kwh, intensity_actual, intensity_baseline, amount_g, balance_before_g, balance_after_g, reference_event_id, idem_key, details, prev_hash, hash`.

```
hash_n = SHA-256( canonical_json({all fields above except hash}) )      prev_hash_1 = 64 × "0"
canonical_json: keys sorted, separators (",", ":"), ASCII, Decimals as exact strings
```

`verify_chain` checks:
- sequence contiguity (reordering, insertion and deletion),
- `prev_hash` linkage,
- recomputed hashes (modification),
- balance continuity (`before + amount = after`, and `before = previous after`),
- duplicate idempotency keys,
- and, optionally, the trusted head hash, which catches truncation of the newest records.

**Limit.** Anyone who can rewrite the entire database can also recompute every hash. A hash chain proves integrity only **relative to a trusted chain head kept elsewhere**. The UI lets you save the head as a checkpoint, and real deployments should publish it externally (a signed log, a git commit, an email to the auditor). The tamper demo alters an **in-memory copy** and never the stored ledger.

## 8. Job state machine

```
pending → queued → running → completed
             │  ↘        ↘ ↕ paused
             │   deferred ─→ running         running/paused → failed | cancelled
             └──────────────→ cancelled       queued/deferred → cancelled
```

`Engine.transition` rejects anything else with `InvalidTransition` (HTTP 409 at the API).

## 9. Edge cases handled

| Case | Behaviour |
|---|---|
| Deadline impossible at creation | rejected with HTTP 422 (`deadline_offset_min < runtime_min`) |
| No feasible window left | run at the earliest capacity and log "deadline at risk"; the miss is flagged, the job continues best-effort and earns no credit |
| Several simultaneous emergencies | first in line takes the reserve worker; the rest use free capacity or wait (logged) |
| Starvation | the optional `max_wait_min` forces a start (background jobs in experiments use 20 h) |
| Duplicate API request | the `idempotency_key` returns the existing job (HTTP 200 instead of 201) |
| Duplicate ledger event | the `idem_key` unique constraint in the DB, plus `DuplicateLedgerEvent` in the engine |
| Over-crediting | applied credit capped at the balance; the balance can never go negative |
| Failed job | debt for the energy already used is booked; the credit is denied |
| Cancelled running job | partial debt booked; the credit is denied |
| No green window at all (`dirty_flat` profile) | debt cannot be repaid. The controller still meets deadlines, and the projection shows the debt outstanding at the horizon. |
| Provider down or invalid data | error reported; no simulated value is relabelled as live |
| Process restart | all state is reloaded from the DB; the ledger verifies against the pre-restart head (tested) |
