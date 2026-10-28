# Proposal and architecture document — content

The Word file **`docs/9_[REGISTRATION_NO]_Carbon_Debt_Computing.docx`** is generated from `tools/build_proposal.js` and follows the structure the assignment requires. Rebuild it after editing your details:

```powershell
cd tools
npm install            # first time only
node build_proposal.js --name "Your Name" --reg "YOURREGNO" --programme "B.Tech CSE" --course "Cloud Computing" --faculty "Prof. ..."
```

With `--reg`, the output is named `9_<REG>_Carbon_Debt_Computing.docx` as required (`[Challenge_Number]_[Registration No.]_[Project_Title].docx`). Without arguments, it keeps clearly marked placeholders.

## Sections

1. **Title page:** project title, Challenge 9, student details (placeholders), date.
2. **Problem statement and objectives:** emergency computing at high carbon intensity; objectives O1–O6 (ledger, priority inversion, throttling, verified repayment, deadline safety, measurable results).
3. **Proposed novelty:** debt memory that changes future scheduling; verified counterfactual credits without banking; deadline-safe progressive throttling; a predictive planner with debt projection; a hash-chained audit ledger; a single deterministic engine for live and experimental use.
4. **System architecture:** block diagram (`diagrams/architecture.png`) and a component table.
5. **Flowchart and scheduling sequence:** per-slot flowchart, scenario sequence and job state machine.
6. **Hardware and software requirements:** laptop specification, OS, runtimes, libraries, APIs (India Energy Atlas), telemetry (Windows Energy Meter / Intel RAPL, psutil), Docker and cloud options.
7. **Algorithms and formulas:** emissions, debt, savings, credit, throttled power, bands, planner steps, hash chain.
8. **Measurement methodology:** labels, estimated energy, simulated or live intensity, host telemetry, uncertainty.
9. **Experimental design and results:** four policies, 10 seeds × 36 jobs, metrics, the results table, the demo scenario and the sweep, all labelled *SIMULATED*. The assignment's "expected outcomes" are given as the measured simulation results, not as promises.
10. **Limitations and future scope:** real meters, Kubernetes integration, forecast uncertainty, marginal emissions, cgroups v2 adapter, external ledger anchoring.
11. **References:** only sources actually used (API documentation and the libraries in the build).

## Placeholders you must fill

| Placeholder | Where |
|---|---|
| Student name, registration number, programme, course, faculty | `node build_proposal.js --name … --reg …` (title page and file name) |
| `[STUDENT NAME]`, `[REGISTRATION_NO]` | `docs/poster/poster.html` header, before printing |
| Date | generated automatically (the build date) |

The registration number was **not** guessed from other files on your computer; enter it yourself.
