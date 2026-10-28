// Builds the Word proposal & architecture document required by the assignment.
//   node build_proposal.js --name "Full Name" --reg "REGNO" --programme "..." --course "..." --faculty "..."
// Numbers are read from docs/results/*.json (produced by tools/generate_results.py).
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, ImageRun, Table, TableRow, TableCell,
  WidthType, ShadingType, BorderStyle, PageBreak, LevelFormat, Footer, PageNumber, TableOfContents,
} = require("docx");

const ROOT = path.resolve(__dirname, "..");
const DOCS = path.join(ROOT, "docs");
const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, cur, i, arr) => (cur.startsWith("--") ? [...acc, [cur.slice(2), arr[i + 1]]] : acc), []),
);
const student = {
  name: args.name || "[STUDENT NAME]",
  reg: args.reg || "[REGISTRATION_NO]",
  programme: args.programme || "[PROGRAMME]",
  course: args.course || "[COURSE CODE / NAME]",
  faculty: args.faculty || "[FACULTY NAME]",
};
const results = JSON.parse(fs.readFileSync(path.join(DOCS, "results", "experiment_results.json"), "utf8"));
const scenario = JSON.parse(fs.readFileSync(path.join(DOCS, "results", "scenario_results.json"), "utf8"));
const agg = results.aggregates;
const POL = ["fifo", "threshold", "debt_reactive", "debt_predictive"];
const LABEL = { fifo: "FIFO / priority", threshold: "Threshold deferral", debt_reactive: "Debt controller (no forecast)", debt_predictive: "Predictive debt controller" };
const fmt = (v, d = 0) => Number(v).toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (p, k) => { const r = agg.fifo[k].mean; return `${(((agg[p][k].mean - r) / r) * 100).toFixed(1)}%`; };

// ---------------------------------------------------------------- helpers
const FONT = "Calibri";
const ACCENT = "5B4BD6";
const CONTENT_W = 9026; // A4 width 11906 − 2 × 1440 margins (DXA)

const p = (text, opts = {}) => new Paragraph({ spacing: { after: 120, line: 288 }, ...opts, children: runs(text) });
function runs(text) {
  // **bold** segments
  return String(text).split(/(\*\*[^*]+\*\*)/).filter(Boolean).map((t) =>
    t.startsWith("**") ? new TextRun({ text: t.slice(2, -2), bold: true }) : new TextRun(t));
}
const h1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun(t)] });
const h2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const bullet = (t) => new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 60, line: 276 }, children: runs(t) });
const numbered = (t) => new Paragraph({ numbering: { reference: "numbers", level: 0 }, spacing: { after: 60, line: 276 }, children: runs(t) });
const formula = (t) => new Paragraph({ spacing: { before: 60, after: 60 }, indent: { left: 400 },
  children: [new TextRun({ text: t, font: "Consolas", size: 19 })] });
const caption = (t) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 },
  children: [new TextRun({ text: t, italics: true, size: 18, color: "555555" })] });

function pngSize(file) {
  const b = fs.readFileSync(file);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20), data: b };
}
function image(rel, widthPx = 600) {
  const { w, h, data } = pngSize(path.join(DOCS, rel));
  return new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 },
    children: [new ImageRun({ type: "png", data, transformation: { width: widthPx, height: Math.round((widthPx * h) / w) } })] });
}

const border = { style: BorderStyle.SINGLE, size: 4, color: "BBBBBB" };
const borders = { top: border, bottom: border, left: border, right: border };
function table(header, rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  const cell = (text, isHead, w) => new TableCell({
    borders, width: { size: w, type: WidthType.DXA },
    shading: isHead ? { fill: "EFECFF", type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ children: [new TextRun({ text: String(text), bold: isHead, size: 19 })] })],
  });
  return new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({ tableHeader: true, children: header.map((t, i) => cell(t, true, widths[i])) }),
      ...rows.map((r) => new TableRow({ children: r.map((t, i) => cell(t, false, widths[i])) }))],
  });
}
const spacer = () => new Paragraph({ spacing: { after: 120 }, children: [] });

// ---------------------------------------------------------------- content
const today = new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
const title = [
  new Paragraph({ spacing: { before: 2400 }, children: [] }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Carbon Debt Computing", bold: true, size: 56, color: "17161A" })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 400 }, children: [new TextRun({ text: "A Deadline-Aware Carbon Debt Controller", size: 32, color: ACCENT })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [new TextRun({ text: "Project Proposal and Architecture Document", size: 26 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 1200 }, children: [new TextRun({ text: "Challenge 9: Carbon Debt Computing (individual challenge)", size: 24 })] }),
  table(["Field", "Details"], [
    ["Student name", student.name], ["Registration number", student.reg], ["Programme", student.programme],
    ["Course", student.course], ["Faculty", student.faculty], ["Team", "Individual submission"], ["Date", today],
  ], [3000, 6026]),
];

const body = [
  new Paragraph({ pageBreakBefore: true, spacing: { after: 200 }, children: [new TextRun({ text: "Contents", bold: true, size: 32 })] }),
  new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }),
  p("Right-click the contents list and choose Update Field if page numbers are missing.", { children: [new TextRun({ text: "Right-click the contents list and choose Update Field if page numbers are missing.", italics: true, size: 18, color: "777777" })] }),

  h1("1. Problem statement and objectives"),
  p("Cloud platforms increasingly shift flexible workloads to times when the electricity grid is cleaner. Emergency workloads, such as a hospital triage-model failover, a flood-alert ensemble recomputation or a fraud-detection retrain, cannot wait. They must run immediately, even when the grid is fossil-heavy. Existing carbon-aware schedulers handle these as exceptions and then forget them: the excess emissions are never recorded against the system, and nothing changes afterwards to compensate."),
  p("This project treats those excess emissions as **carbon debt**. Debt is recorded in an auditable ledger, and the scheduler is obliged to repay it by moving future flexible work into green (low-carbon) periods. While the debt is outstanding, non-critical workloads are progressively throttled, and no job is ever pushed past its deadline."),
  h2("Objectives"),
  numbered("**O1 — Debt ledger.** Record policy-defined excess emissions of high-carbon execution in an append-only, hash-chained ledger."),
  numbered("**O2 — Priority inversion.** While debt is outstanding, direct eligible flexible capacity into strictly green time slots until the balance returns to zero."),
  numbered("**O3 — Throttling.** Automatically throttle or defer non-critical workloads when debt crosses configured thresholds, without ever throttling emergencies."),
  numbered("**O4 — Verified repayment.** Grant repayment credit only for deliberate, deadline-meeting deferrals against a counterfactual baseline recorded in advance."),
  numbered("**O5 — Deadline safety and prediction.** Never defer work past its deadline, and project the debt path over a forecast horizon."),
  numbered("**O6 — Measurable outcomes.** Demonstrate live operation and compare against baselines with reproducible quantitative experiments."),

  h1("2. Proposed novelty"),
  bullet("**Debt with memory.** Unavoidable emergency emissions persist as a debt that changes later scheduling decisions. In typical carbon-aware schedulers, decisions depend only on the current or forecast intensity."),
  bullet("**Verified counterfactual credits.** The baseline intensity is fixed in a hash-chained DEFERRAL_RECORDED event when the controller defers a job. The credit is max(0, E·I_baseline − actual emissions), granted once, only if the deadline is met and no operator override occurred. Surplus credit is not banked, so green work cannot pre-pay future emergencies."),
  bullet("**Repayment-value priority inversion.** During repayment, waiting jobs are ranked by the debt they can repay (energy × intensity drop) instead of nominal priority."),
  bullet("**Deadline-safe progressive throttling.** Debt bands map to 100/50/20%/paused capacity for normal and background work. A level is applied only if the job still finishes two slots before its deadline, and throttling's energy penalty (static power) is modelled honestly."),
  bullet("**Predictive debt controller.** An earliest-deadline-first capacity reservation over the forecast, a green-only window restriction while in debt, a feasibility repair pass, and a debt projection that triggers proactive throttling."),
  bullet("**One deterministic engine for live operation and experiments.** The dashboard and the policy comparison are produced by the same Decimal-exact code, so experimental results are exactly what the system does."),

  h1("3. System architecture"),
  p("The system is a simulated cloud scheduler that runs locally by default, with an optional real cloud deployment of the controller and dashboard. All logic runs in the backend; the browser only displays persisted data."),
  image("diagrams/architecture.png"),
  caption("Figure 1. Block diagram of the system."),
  h2("Component breakdown"),
  table(["Component", "Technology", "Responsibility"], [
    ["Dashboard", "React, TypeScript, Vite, Tailwind, Recharts", "Overview, Workloads, Carbon controller, Debt ledger, Experiments, Telemetry & settings"],
    ["REST API", "FastAPI, Pydantic", "Validated endpoints, OpenAPI docs, admin token, CORS, structured logs, health check"],
    ["SimulationService", "Python, SQLAlchemy", "Per 15-minute tick: rebuild engine from DB, step, persist all new records in one transaction; autoplay; scenario"],
    ["Engine and policies", "Pure Python, Decimal", "Job state machine, capacity and emergency reserve, energy/emissions/debt, FIFO/threshold/debt/predictive policies"],
    ["Predictive planner", "Pure Python", "EDF reservation, green-only windows under debt, repair pass, debt projection"],
    ["Accounting and ledger", "SHA-256, canonical JSON", "Debt and credit rules, idempotency, balance ≥ 0, verification and tamper detection"],
    ["Experiment runner", "Pure Python", "Identical seeded traces and curves per policy; metrics; parameter sweeps; CSV/JSON export"],
    ["Live mode", "httpx, psutil, PDH (ctypes)", "India Energy Atlas grid feed, Windows process monitor, measured CPU-package energy, bounded CPU workers"],
    ["Persistence", "SQLite / PostgreSQL", "Jobs, decisions, execution attempts, ledger, readings, timeline, experiments"],
  ], [2000, 2600, 4426]),

  h1("4. Flowchart and scheduling sequence"),
  image("diagrams/flowchart.png"),
  caption("Figure 2. Processing of one scheduling slot by the predictive debt controller."),
  image("diagrams/sequence.png"),
  caption("Figure 3. Emergency-to-green repayment scenario (demonstration)."),
  image("diagrams/states.png", 560),
  caption("Figure 4. Job state machine; any other transition is rejected."),

  h1("5. Hardware and software requirements"),
  h2("Hardware"),
  table(["Item", "Used for development / demo", "Notes"], [
    ["Laptop", "Windows 11, Intel Core i5-13500H, battery-powered laptop", "Any machine with Python 3.11 and Node 20 works"],
    ["Power telemetry", "Windows Energy Meter counter (Intel RAPL, CPU package)", "Measured package energy; no admin rights needed"],
    ["Optional", "Linux host with Intel RAPL", "CPU package power; needs read permission"],
    ["Cloud (optional)", "1 small VM (e.g. Azure B2ats_v2 / B1ms)", "Docker Compose + Caddy HTTPS"],
  ], [2000, 3800, 3226]),
  h2("Software, APIs and frameworks"),
  table(["Layer", "Software"], [
    ["Backend", "Python 3.11, FastAPI 0.115, Pydantic 2.10, SQLAlchemy 2.0, Uvicorn, httpx, psutil, pytest"],
    ["Frontend", "React 18, TypeScript 5.6, Vite 5, Tailwind CSS 3.4, Recharts 2.13, lucide-react"],
    ["Data", "SQLite (default), PostgreSQL via psycopg 3 (cloud option)"],
    ["Carbon-intensity API", "India Energy Atlas (api.energymap.in, X-API-Key; free Sandbox/Student plans, all-India)"],
    ["Telemetry", "psutil (processes, CPU, memory); Windows Energy Meter via PDH; Linux powercap RAPL"],
    ["Deployment", "Docker, Docker Compose, nginx, Caddy (Let's Encrypt TLS), optional Render blueprint"],
  ], [2600, 6426]),

  h1("6. Algorithms and formulas"),
  p("Time advances in 15-minute slots. Units: kWh, gCO₂e/kWh, gCO₂e, W. Accounting uses Decimal arithmetic, quantised per slot."),
  formula("P(c)            = P_declared × (s + (1 − s)·c)            s = 0.30"),
  formula("energy_slot     = P(c) × minutes / 60 / 1000             [kWh]"),
  formula("gross_emissions = Σ energy_slot × I_slot                 [gCO₂e]"),
  formula("debt            = Σ energy_slot × max(0, I_slot − I_thr)  I_thr = 350"),
  formula("est_savings     = E × max(0, I_now − I_candidate)"),
  formula("credit          = max(0, E_full × I_baseline − gross_emissions)"),
  formula("credit_applied  = min(credit, outstanding);  outstanding = Σdebt − Σcredit_applied ≥ 0"),
  formula("hash_n          = SHA-256(canonical_json(record_n fields ‖ prev_hash))"),
  h2("Policies"),
  bullet("**Emergency precedence (all policies).** Start immediately at 100%; one worker is reserved; never throttled."),
  bullet("**Threshold.** Run if I ≤ I_thr, otherwise defer one slot while start + runtime ≤ deadline remains true."),
  bullet("**Debt controller.** If debt > 0, flexible jobs start only in green slots (I ≤ 200), ranked by repayment value; otherwise the threshold rule applies."),
  bullet("**Predictive controller.** Every slot, reserve capacity earliest-deadline-first and choose the lowest-carbon feasible window (only fully green windows while in debt, if any fit), with a 2-slot deadline margin and a repair pass. Delay only for a saving of at least 5 g. Project the debt path and raise the throttle band early if debt cannot be repaid within the horizon."),
  h2("Progressive throttling"),
  table(["Effective debt", "State", "Normal", "Background"], [
    ["0", "Normal", "100%", "100%"], ["0 – 100 g", "Repaying", "100%", "100%"], ["100 – 400 g", "Soft throttle", "100%", "50%"],
    ["400 – 800 g", "Hard throttle", "50%", "20%"], ["≥ 800 g", "Critical", "20%", "Paused"],
  ], [2400, 2400, 2113, 2113]),
  p("Throttling applies only outside green windows, never to emergencies, and only when the job still finishes two slots before its deadline."),

  h1("7. Measurement methodology"),
  bullet("**Labels.** Every value is SIMULATED, MANUAL_OVERRIDE, LIVE_ACTUAL / LIVE_FORECAST, ESTIMATED, MEASURED or UNAVAILABLE. A simulated value is never shown as live."),
  bullet("**Energy (ESTIMATED).** Declared job power × runtime with a static/dynamic throttle model. A real SHA-256 proxy kernel runs for each job-slot and its CPU time is recorded as execution evidence, not as job energy."),
  bullet("**Grid intensity.** Simulation mode: a deterministic, seeded simulated curve (solar-midday profile, 3% noise). Live mode: the all-India reading from India Energy Atlas (polled every 20 minutes within the free 100-calls/day quota), with provider, region, timestamp and freshness displayed; the provider models the fuel mix (±3%)."),
  bullet("**Live energy (MEASURED, attributed).** CPU-package energy from the Windows Energy Meter counter (Intel RAPL), shared to each managed job by its share of busy CPU time; processes, CPU and memory from psutil. Ordinary Windows programs are only observed."),
  bullet("**Uncertainty.** Declared power may differ from reality by tens of percent; provider intensities are averages, not marginal factors; forecast uncertainty is not modelled. Comparisons between policies are fair because they share identical inputs."),

  h1("8. Experimental design and results"),
  p("**All results in this section come from deterministic simulation (SIMULATED energy and grid). They were produced by the implemented system with tools/generate_results.py and are not hardware measurements.**"),
  h2("Design"),
  bullet("Four policies on identical inputs: FIFO/priority, threshold deferral, the debt controller without forecast, and the predictive debt controller."),
  bullet(`${results.request.seeds.length} seeds. Each trace has ${results.trace_summary.jobs} jobs (4 emergency, 18 normal, 14 background); 4 workers with 1 reserved; solar-midday grid; I_thr = 350, green ≤ 200 gCO₂e/kWh.`),
  bullet("Metrics: gross emissions, debt incurred, credits, final and peak debt, deadline misses, delay, energy, throttle actions and decision time."),
  h2("Policy comparison (mean over seeds)"),
  table(["Policy", "Emissions (g)", "vs FIFO", "Debt incurred (g)", "Final debt (g)", "Misses/run", "Delay (min)"],
    POL.map((k) => [LABEL[k], fmt(agg[k].gross_emissions_g.mean), k === "fifo" ? "—" : pct(k, "gross_emissions_g"),
      fmt(agg[k].total_debt_g.mean), fmt(agg[k].final_debt_g.mean), fmt(agg[k].deadline_misses.mean, 1), fmt(agg[k].avg_delay_min.mean)]),
    [2300, 1150, 900, 1300, 1150, 1000, 1226]),
  spacer(),
  image("results/policy_comparison.png", 620),
  caption("Figure 5. Mean ± 1 standard deviation across seeds (SIMULATED)."),
  h2("Demonstration scenario"),
  table(["Policy", "Gross emissions (g)", "Debt incurred (g)", "Final debt (g)", "Deadline misses"],
    POL.map((k) => [LABEL[k], fmt(scenario[k].gross_emissions_g), fmt(scenario[k].total_debt_g), fmt(scenario[k].final_debt_g), String(scenario[k].deadline_misses)]),
    [2800, 1700, 1700, 1500, 1326]),
  spacer(),
  image("results/scenario_timeline.png"),
  caption("Figure 6. Demo scenario under the predictive controller: debt created in the morning peak and repaid in the green window."),
  h2("Findings"),
  bullet(`Against FIFO, the predictive controller changed gross emissions by ${pct("debt_predictive", "gross_emissions_g")} and debt incurred by ${pct("debt_predictive", "total_debt_g")}, with ${fmt(agg.debt_predictive.deadline_misses.mean, 1)} deadline misses per run (threshold: ${fmt(agg.threshold.deadline_misses.mean, 1)}).`),
  bullet(`Forecasting matters for deadlines: the debt controller without a forecast missed ${fmt(agg.debt_reactive.deadline_misses.mean, 1)} per run, because jobs pile up at their last feasible slot. It reached slightly lower emissions (${fmt(agg.debt_reactive.gross_emissions_g.mean)} g) and final debt (${fmt(agg.debt_reactive.final_debt_g.mean)} g).`),
  bullet(`The cost of carbon awareness is delay for flexible work (average completion delay ${fmt(agg.debt_predictive.avg_delay_min.mean)} min vs ${fmt(agg.fifo.avg_delay_min.mean)} min for FIFO), plus ${fmt(((agg.debt_predictive.energy_kwh.mean / agg.fifo.energy_kwh.mean) - 1) * 100, 1)}% more energy from throttling.`),
  bullet(`In the demo, ${fmt(scenario.debt_predictive.total_debt_g)} g of debt was fully repaid by verified credits, with no missed deadlines; the hash chain verified (${scenario.debt_predictive.ledger_entries} entries).`),
  image("results/green_threshold_sweep.png"),
  caption("Figure 7. Sweep of the green threshold for the predictive controller."),

  h1("9. Limitations and future scope"),
  h2("Limitations"),
  bullet("The cluster is simulated locally; workloads are not dispatched to real cloud servers."),
  bullet("Job energy is estimated from declared power; no meter is attributed to simulated jobs."),
  bullet("The default grid curve is illustrative, and forecast uncertainty is not modelled."),
  bullet("Debt is a policy-defined quantity; credits record avoided future emissions and do not erase past emissions."),
  bullet("The hash chain is tamper-evident only relative to an externally kept head hash."),
  bullet("Throttling is scheduler-level (capacity share), with a linear power model."),
  h2("Future scope"),
  bullet("Dispatch decisions to Kubernetes Jobs or a cloud batch queue, using node power from IPMI/Redfish or provider APIs."),
  bullet("Probabilistic forecasts with a risk-aware planner, and marginal emission factors."),
  bullet("An OS-level cgroups v2 CPU-quota adapter on Linux hosts."),
  bullet("Periodic anchoring of the ledger head to an external append-only log."),
  bullet("Multi-tenant debt budgets per application or team."),

  h1("10. References"),
  numbered("India Energy Atlas developer documentation, https://www.energymap.in/developer (carbon-intensity/latest, forecast/carbon-intensity, authentication, quotas)."),
  numbered("psutil documentation, https://psutil.readthedocs.io/; Microsoft, Performance Data Helper (PDH) API and the Energy Meter counter set."),
  numbered("Linux kernel documentation, Power Capping Framework (powercap / Intel RAPL), https://docs.kernel.org/power/powercap/powercap.html."),
    numbered("FastAPI documentation, https://fastapi.tiangolo.com/; SQLAlchemy 2.0 documentation, https://docs.sqlalchemy.org/."),
  numbered("React, https://react.dev/; Recharts, https://recharts.org/; Vite, https://vitejs.dev/."),
  numbered("Caddy web server (automatic HTTPS), https://caddyserver.com/docs/; Microsoft Azure for Students, https://azure.microsoft.com/free/students/."),
];

const doc = new Document({
  creator: student.name,
  title: "Carbon Debt Computing — Proposal and Architecture",
  description: "Challenge 9 project proposal",
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: FONT, color: "17161A" }, paragraph: { spacing: { before: 240, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 25, bold: true, font: FONT, color: ACCENT }, paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 280 } } } }] },
      { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 360 } } } }] },
    ],
  },
  features: { updateFields: true },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [
      new TextRun({ text: "Carbon Debt Computing — Challenge 9    ", size: 16, color: "888888" }),
      new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "888888" })] })] }) },
    children: [...title, ...body],
  }],
});

const regPart = args.reg ? args.reg.replace(/[^A-Za-z0-9]/g, "") : "[REGISTRATION_NO]";
const out = path.join(DOCS, `9_${regPart}_Carbon_Debt_Computing.docx`);
Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(out, buf);
  console.log("Wrote", out);
});
