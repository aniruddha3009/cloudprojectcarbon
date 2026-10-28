# 10-minute demonstration script

## Before the evaluator arrives (10 min earlier)

1. Plug in the laptop and connect to Wi-Fi (Wi-Fi is needed only for the live grid panel).
2. `powershell -ExecutionPolicy Bypass -File .\start-dev.ps1`, then wait for the browser at http://127.0.0.1:5173.
3. Switch to **Live**, press **Start monitoring**, and check that the Telemetry page's *Electricity grid* panel says **Connected** (India Energy Atlas). Then switch back to **Simulation** for the main demo.
4. Experiments: confirm a completed *Default comparison* run exists. If not, press **Run experiment**; it takes about 1 second.
5. Carbon controller: policy = *Predictive carbon debt controller*, profile = *solar midday*, override off.
6. Overview: press **Run emergency-to-green scenario** once as a rehearsal, then leave it finished.
7. Put the printed poster on the desk.

## Timeline

| Time | Show | Say | Expected on screen |
|---|---|---|---|
| 0:00–1:00 | Poster | "Emergency computing sometimes must run when the grid is dirty. I treat the excess as **carbon debt** in a tamper-evident ledger, and the scheduler **repays** it by moving flexible work into green windows, without breaking deadlines." | — |
| 1:00–1:30 | Overview top bar | "Everything runs on the FastAPI backend. The browser only displays it. The grid is simulated and labelled as such; energy is estimated." | the *Simulated grid* chip |
| 1:30–2:00 | Top bar → **Run emergency-to-green scenario** → confirm | "This resets the demo, loads eight jobs at 06:00 and the backend advances one 15-minute slot every 0.7 s." | clock starts at 06:00 |
| 2:00–3:30 | Overview while it plays | "06:45: the hospital triage failover is an **emergency**, so it starts immediately at 550–650 g/kWh. The violet debt line rises. The controller enters soft, hard, then critical bands. The log-compaction job is throttled to 50%, then **paused**, then forced back to 100% at 08:30 to meet its 09:30 deadline. Billing cannot wait, so deadline protection runs it." | debt chip rises; Gantt shows red segments of varying height |
| 3:30–4:30 | Carbon controller (while playing) | "Priority inversion: the ETL and the hyper-parameter sweep are **deferred to 12:00**. Here is the reason recorded at decision time: intensity falls from 633 to 142, the deadline is still feasible, debt is outstanding. The dashed line is the **predicted** debt path." | Planned placements and projection chart |
| 4:30–5:30 | Overview at ~12:00–13:30 | "11:30: the green window opens. 12:00: **repayment jobs** start, ranked by repayment value, so the low-priority sweep goes ahead of normal work. As each finishes, a verified credit is booked. At 13:30 the debt reaches **zero** and the inversion lifts." | all 7 milestones ticked; equation e.g. 1,059 g − 1,059 g = 0 g |
| 5:30–6:30 | Click *Nightly ETL backfill* → Carbon receipt | "Every job gets a receipt: energy and its source, the baseline of 633 recorded when it was deferred, the actual 142, the credit of 491 g, and the ledger hashes." | receipt tab |
| 6:30–7:45 | Debt ledger | "The ledger is append-only and **SHA-256 hash-chained**. Verified. Now I tamper with a *copy*: halve a debt amount → detected at that entry. The stored ledger is still verified. Honest limit: a hash chain is only as trustworthy as the head hash you keep elsewhere, so I can checkpoint it." | Verified → Tamper demo shows Tampered |
| 7:45–9:00 | Experiments | "Same engine, 10 seeded traces, 4 policies on identical inputs. Against FIFO, the predictive controller cuts emissions 17% and debt 46%, with deadline misses equal to the threshold policy. The controller without forecasting misses three times more deadlines because jobs pile up at their last feasible moment. The cost of all of this is delay for flexible work." | bar chart with error bars |
| 9:00–9:40 | Live mode → Telemetry | "Live mode: real Indian grid intensity from India Energy Atlas, with its timestamp and freshness. The process table is this laptop, refreshed every 2.5 seconds; I open Notepad and it appears. CPU-package energy is measured by the Windows Energy Meter (Intel RAPL), and managed jobs get their share by CPU time." | grid reading; process appears; package watts |
| 9:40–10:00 | Close | "Limitations: simulated cluster, estimated energy, illustrative curve. Credits record avoided *future* emissions; they never erase past ones." | — |

## Optional extras (if asked)

- **Change a setting live.** Carbon controller → set the green threshold to 250 → Save. A *Settings changed* decision appears, and new decisions use it.
- **Grid event.** Enable *Inject a grid event* from 12 to 13 h at 650 → Save → Run scenario. Repayment shifts around the injected spike.
- **Add an emergency.** Workloads → Add job → Emergency, 1,200 W, 60 min, deadline 90 → Step (15 min). It starts immediately.
- **Show the API.** http://127.0.0.1:8000/docs.

## Recovery steps

| Problem | Recovery |
|---|---|
| Browser shows "Backend unreachable" | Look at the backend window for a traceback. Close it and rerun `start-dev.ps1`. |
| Scenario looks stuck | Press Play. If the clock is at 16:00 it has finished; press the scenario button again. |
| Messy data after experiments with settings | Carbon controller: policy predictive, profile solar midday, override off, then Run scenario (it resets jobs and the ledger). |
| No internet | Skip the live grid panel and say: "it reports unavailable rather than inventing data." |
| Port already in use | Close the old windows; `Get-NetTCPConnection -LocalPort 8000` shows the process. |
| Worst case | `Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/scenario/run -ContentType application/json -Body '{"mode":"instant"}'` completes the whole scenario in about 1 s. |
