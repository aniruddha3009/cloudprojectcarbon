# Poster (one page)

The printable poster is **`docs/poster/poster.html`** (A3 portrait, which also scales to A4). A pre-rendered PDF is at **`docs/poster/poster.pdf`**.

**To print or export:** open `poster.html` in Edge or Chrome → Ctrl+P → Destination *Save as PDF* or your printer → Paper **A3** (or A4, "Fit to page") → Margins *None* → tick **Background graphics**.

Before printing, replace `[STUDENT NAME]` and `[REGISTRATION_NO]` in `poster.html` (search for the square brackets).

## Content

**Title:** Carbon Debt Computing — a deadline-aware carbon debt controller (Challenge 9)

**Problem.** Emergency workloads must sometimes run when the grid is fossil-heavy. Existing carbon-aware schedulers defer flexible work, but they forget the unavoidable emissions and never make them up.

**Idea.** Treat the excess as **carbon debt**:
1. **Book** the excess above 350 gCO₂e/kWh into a SHA-256 hash-chained ledger.
2. **Invert priority**: while debt > 0, flexible work runs only in green windows (≤ 200), ranked by repayment value.
3. **Throttle** non-critical work by debt band (100 / 50 / 20% / paused), deadline-safe, never emergencies.
4. **Repay** with *verified* credits: baseline recorded at deferral, deadline met, no duplicates, no banking.
5. **Predict** the debt path with a capacity-aware forecast planner.

**Architecture.** React dashboard → FastAPI → SimulationService (DB ⇄ engine per 15-min slot) → deterministic core (engine, policies, planner, accounting, hash chain) → SQLite/PostgreSQL; plus India Energy Atlas (live grid intensity) and the Windows Energy Meter / RAPL with psutil (live laptop telemetry). See `diagrams/architecture.png`.

**Results** (10 seeds × 36 jobs, simulated grid):

| | FIFO | Threshold | Debt ctrl | Predictive |
|---|---|---|---|---|
| Emissions | 20.6 kg | 17.6 kg | 16.9 kg | 17.2 kg (−16.7%) |
| Debt incurred | 5.4 kg | 3.0 kg | 3.2 kg | 2.9 kg (−46.5%) |
| Deadline misses / run | 0.2 | 1.3 | 3.8 | 1.3 |

Demo scenario: 1,059 g of emergency debt repaid to zero by 13:30, with no missed deadlines.

**Honesty box.** Energy is estimated, the grid is simulated in Simulation mode (Live mode uses India Energy Atlas, which the provider models), and the cluster is local. Credits record avoided future emissions; they do not erase past ones. The hash chain is trustworthy only relative to an external head checkpoint.
