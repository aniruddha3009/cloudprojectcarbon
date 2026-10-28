# Viva preparation

Short, accurate answers. The numbers come from `docs/results/` (10 seeds).

## Concept and novelty

**What is carbon debt?**
The excess emissions of work run above a carbon-intensity threshold: `energy × max(0, intensity − 350)`. It is a *policy* quantity, like a budget overdraft. It is not the total footprint, which is shown separately as gross emissions.

**What is novel compared with an ordinary carbon-aware scheduler?**
Ordinary schedulers only defer flexible jobs to cleaner times. Here:
1. Unavoidable emergency emissions are **remembered** as a debt in an auditable ledger.
2. That debt **changes future behaviour**: priority inversion confines flexible work to green slots, and progressive throttling depends on the debt band.
3. Repayment credits are **verified against a counterfactual baseline recorded at deferral time**, with no duplicates and no banking.
4. The whole scheme is deadline-safe, and a forecast planner projects the debt path.

**Explain "priority inversion" in your system.**
While debt > 0, a flexible job's right to run is decided by carbon, not by nominal priority. It may start only in green slots unless its deadline forces otherwise. Waiting jobs are ranked by *repayment value* (energy × (baseline − current intensity)). In the demo, the priority-5 hyper-parameter sweep starts before priority-3 work because it repays more debt. Once the balance reaches zero, a `DEBT_CLEARED` event lifts the inversion.

**Is this a dashboard or a real system?**
The scheduler runs on the backend. Every 15-minute slot it makes decisions, executes a real CPU proxy kernel per job, and writes decisions, execution attempts, ledger entries and timeline points to the database in one transaction. The frontend only reads. Experiments run the *same* engine on seeded traces. There are 76 automated tests.

## Accounting

**How is a credit calculated, and why is it defensible?**
`credit = max(0, E_full × I_baseline − actual_emissions)`. The baseline is the forecast mean intensity of the window the job would have used had it started *at deferral time*. It is recorded in a hash-chained `DEFERRAL_RECORDED` event before the outcome is known. Credit requires: a deliberate controller deferral (a worker was free, so it was not a capacity wait), completion, the deadline met, no previous credit, and no operator override.

**Can credits make the balance negative, or be saved for later?**
No. The applied credit is `min(credit, balance)`, and the surplus is recorded but not banked. Otherwise a quiet afternoon could "pre-pay" tomorrow's emergency, which would defeat the purpose.

**Do credits erase emissions?**
No. Emissions that happened are permanent and stay visible as gross emissions. A credit records emissions *avoided in the future* by shifting work; it settles the policy debt, not the physics.

**Why not compare intensities directly?**
Throttling increases energy (static power), so comparing *total emissions* charges that penalty against the credit. For an un-throttled job the two forms are identical.

**Why use Decimal?**
Float rounding would make ledger hashes and balances platform-dependent. Values are quantised per slot (9 dp kWh, 6 dp g) with banker's rounding and stored as exact strings.

## Scheduling

**How do you guarantee deadlines?**
A job is deferred only to a window where `start + runtime ≤ deadline` *and* capacity is reserved. The planner reserves earliest-deadline-first and keeps a 2-slot margin, and a repair pass pins earlier jobs if a later job would be left without a feasible window. Throttling is allowed only if the job still finishes 2 slots early. Emergencies are never deferred or throttled. If a deadline is still missed (capacity overload), the system flags it and denies the credit.

**What does the forecast add? (Predictive vs reactive.)**
With 10 seeds: misses fall from 3.8 to 1.3 per run, and debt incurred is the lowest of all policies (2,880 g vs 3,160 g). Without a forecast, jobs wait slot by slot and then collide at their last feasible moment. The reactive controller does reach slightly lower emissions (16,880 vs 17,197 g) and final debt, because it waits longer for green slots. That trade-off is reported, not hidden.

**Is the planner optimal?**
No. It is a greedy reservation heuristic: EDF order, best window per job, plus repair. An exact formulation would be an integer program over slots × jobs. The heuristic runs in under 1 ms per slot and is explainable.

**How does throttling work, and does it save carbon?**
Throttling is a scheduler-level capacity share (100/50/20%/pause) by debt band, applied outside green windows. It is not OS CPU throttling. Throttling alone raises energy per unit of work by 1.3× at half speed. It helps only by pushing work into cleaner slots and freeing capacity. The predictive controller uses 3% more energy than FIFO but emits 17% less.

**What happens with no green window at all?**
Run the `dirty_flat` profile. The controller cannot repay the debt; it still meets deadlines by running jobs in the least-carbon feasible windows, and the projection shows debt remaining at the horizon. That is the honest outcome.

**Starvation and fairness?**
EDF ordering, an optional `max_wait_min` guard (20 h for background jobs in the traces), and deadline protection.

## Measurement and telemetry

**Where do the energy numbers come from?**
Declared job power × runtime, with a static/dynamic throttle model, labelled ESTIMATED. No meter is attributed to simulated jobs.

**What is actually measured or live?**
In Live mode: (1) Indian grid intensity from the India Energy Atlas API, with its timestamp and freshness. (2) CPU-package energy from the Windows Energy Meter counter (Intel RAPL), shared out to each managed job by its CPU time. (3) Each managed job's own CPU time. (4) The Windows process list, CPU and memory (psutil). In Simulation mode the grid and energy are labelled SIMULATED/ESTIMATED.

**Why don't you use the laptop's power for the jobs?**
It measures the whole laptop, including the screen and browser, not a remote cloud node. Attributing it to simulated jobs would be false precision, so it is displayed separately.

**Is CPU utilisation energy?**
No. It is shown for context only.

**Accuracy?**
Declared power may be off by tens of percent, intensities are provider estimates (average, not marginal), and forecasts are treated as exact. Policy comparisons are fair because all policies share the same estimates; absolute grams are indicative.

## Ledger and security

**Is the ledger tamper-proof?**
It is tamper-*evident*. Any modification, deletion or reordering breaks the SHA-256 chain or the balance continuity, as the demo shows. Someone with full write access can recompute every hash, so integrity holds only against a trusted head hash kept elsewhere (a checkpoint). I would publish the head periodically to an external, append-only location.

**Which fields are hashed?**
All of them except `hash` itself: seq, event id, type, job, sim time, recorded time, energy, intensities, amount, balances, reference id, idempotency key, details and prev_hash. They are serialised as canonical JSON with sorted keys.

**How are duplicates prevented?**
Idempotency keys (`DEBT:<job>`, `CREDIT:<job>`, `DEFERRAL:<job>`) are unique in the engine and in the database. API job creation accepts an `idempotency_key` too.

**Security of a public deployment?**
`X-Admin-Token` for every change, CORS restricted to the site origin, HTTPS via Caddy, no debug mode, a non-root container, secrets only in the server `.env`, and bounded job limits.

## Cloud

**Where is the cloud in this project?**
It is a simulated cloud scheduler (a 4-worker cluster with an emergency reserve) running locally. The application is containerised and ready for a cloud VM (Azure for Students + Docker Compose + Caddy) or Render. Deploying it publishes the controller and dashboard; it does **not** turn the simulated workloads into real cloud executions. A real deployment would put the same policy in front of Kubernetes Jobs or a batch queue: the decision step would emit start/suspend actions instead of updating simulated state.

**Why SQLite?**
It needs zero setup for the demo, and it is durable on a single VM disk. On platforms with ephemeral disks or multiple instances, use PostgreSQL via `DATABASE_URL` (supported).

## Limitations to state proactively

Simulated cluster · estimated energy · illustrative curve · forecast uncertainty not modelled · a policy-defined threshold · linear power model · trust in the hash chain depends on the checkpoint · live per-job energy is a CPU-time share of measured package energy · free India Energy Atlas plans are national only · Docker files not built on the development machine (Docker was not installed).
