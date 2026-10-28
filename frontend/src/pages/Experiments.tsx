import { useEffect, useMemo, useState } from "react";
import { Download, Trash2 } from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Cell, ErrorBar, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, downloadUrl } from "../lib/api";
import { useApp } from "../lib/appState";
import { POLICY_COLORS, POLICY_SHORT, grams, localTime, num, slotClock } from "../lib/format";
import { usePoll } from "../lib/hooks";
import type { Experiment, ExperimentResults, PolicyName } from "../lib/types";
import { ChartLegend } from "../components/charts";
import { Button, ConfirmDialog, Details, EmptyState, ErrorNote, Loading, PageHeader, Panel, TabPanel, Tabs, useToast } from "../components/ui";
import { motion } from "motion/react";

const ALL_POLICIES: PolicyName[] = ["fifo", "threshold", "debt_reactive", "debt_predictive"];
const CHART_METRICS = [
  "gross_emissions_g", "total_debt_g", "final_debt_g", "peak_debt_g", "credits_applied_g",
  "deadline_misses", "avg_delay_min", "energy_kwh", "throttle_actions",
];
const SWEEP_PARAMS: Record<string, string> = {
  debt_intensity_threshold: "Debt threshold (gCO₂e/kWh)",
  green_threshold: "Green threshold (gCO₂e/kWh)",
  debt_hard_g: "Hard debt band (g)",
  static_power_fraction: "Static power share",
};

function fmtMetric(key: string, v: number): string {
  if (key.endsWith("_g")) return grams(v);
  if (key.endsWith("_kwh")) return `${num(v, 2)} kWh`;
  if (key.endsWith("_min")) return `${num(v, 0)} min`;
  if (key.endsWith("_us")) return `${num(v, 0)} µs`;
  return num(v, 1);
}

function Summary({ r }: { r: ExperimentResults }) {
  const agg = r.aggregates;
  const names = Object.keys(agg) as PolicyName[];
  const best = (k: string) => names.reduce((a, b) => (agg[b][k].mean < agg[a][k].mean ? b : a));
  const pred = agg["debt_predictive"];
  const ref = agg[r.reference_policy];
  const lines: string[] = [
    `Lowest gross emissions: ${POLICY_SHORT[best("gross_emissions_g")]} (${grams(agg[best("gross_emissions_g")].gross_emissions_g.mean)} mean).`,
    `Lowest final outstanding debt: ${POLICY_SHORT[best("final_debt_g")]} (${grams(agg[best("final_debt_g")].final_debt_g.mean)}).`,
    `Fewest deadline misses: ${POLICY_SHORT[best("deadline_misses")]} (${num(agg[best("deadline_misses")].deadline_misses.mean, 1)} per run).`,
  ];
  if (pred && ref && r.reference_policy !== "debt_predictive") {
    const d = (k: string) => r.comparisons_vs_reference_pct["debt_predictive"][k];
    const e = d("gross_emissions_g"), debt = d("total_debt_g");
    lines.push(
      `Against ${POLICY_SHORT[r.reference_policy]}, the predictive controller changed gross emissions by ${e === null ? "n/a" : `${e > 0 ? "+" : ""}${num(e, 1)}%`} and incurred debt by ${debt === null ? "n/a" : `${debt > 0 ? "+" : ""}${num(debt, 1)}%`}, at the cost of ${num(pred.avg_delay_min.mean - ref.avg_delay_min.mean, 0)} min more average delay and ${num(pred.deadline_misses.mean - ref.deadline_misses.mean, 1)} more deadline misses per run.`,
    );
  }
  return (
    <ul className="space-y-1.5 text-[14.5px] text-ink-2">
      {lines.map((l) => <li key={l}>{l}</li>)}
      <li className="text-muted">These are computed from this run's data; trade-offs are reported as they came out, not tuned to a target.</li>
    </ul>
  );
}

const KEY_METRICS: { key: string; label: string; help: string; fmt: (v: number) => string; better: "low" | "high" }[] = [
  { key: "gross_emissions_g", label: "Total Carbon Emissions", help: "All carbon the workloads emitted", fmt: (v) => grams(v), better: "low" },
  { key: "final_debt_g", label: "Carbon Debt Remaining", help: "Debt still unpaid at the end", fmt: (v) => grams(v), better: "low" },
  { key: "clean_energy_pct", label: "Clean-Energy Usage", help: "Share of energy used in clean periods", fmt: (v) => `${num(v, 1)}%`, better: "high" },
  { key: "deadline_misses", label: "Deadline Misses", help: "Processes finished late, per run", fmt: (v) => num(v, 1), better: "low" },
];

/** One sentence built only from the measured means; it says nothing the numbers do not support. */
function conclusion(r: ExperimentResults): string | null {
  const a = r.aggregates;
  const p = a["debt_predictive"], f = a["fifo"];
  if (!p || !f || !p.clean_energy_pct || !f.clean_energy_pct) return null;
  const lessDebt = p.final_debt_g.mean < f.final_debt_g.mean;
  const cleaner = p.clean_energy_pct.mean > f.clean_energy_pct.mean;
  const lessCarbon = p.gross_emissions_g.mean < f.gross_emissions_g.mean;
  const extraMisses = p.deadline_misses.mean - f.deadline_misses.mean;
  const good = [lessDebt && "left less carbon debt", cleaner && "used clean electricity more often", lessCarbon && "emitted less carbon"].filter(Boolean) as string[];
  const bad = [!lessDebt && "did not leave less carbon debt", !cleaner && "did not use clean electricity more often"].filter(Boolean) as string[];
  let s = "Compared with FIFO, the predictive controller ";
  s += good.length ? good.join(", ").replace(/, ([^,]*)$/, " and $1") : "showed no carbon improvement";
  if (bad.length) s += `, but ${bad.join(" and ")}`;
  s += extraMisses > 0.05
    ? `. It missed ${num(extraMisses, 1)} more deadline${extraMisses >= 1.05 ? "s" : ""} per run (${num(p.deadline_misses.mean, 1)} vs ${num(f.deadline_misses.mean, 1)}), because it waits for cleaner periods.`
    : `, with no more deadline misses (${num(p.deadline_misses.mean, 1)} vs ${num(f.deadline_misses.mean, 1)} per run).`;
  return s;
}

function KeyResults({ r, threshold }: { r: ExperimentResults; threshold: number }) {
  const names = r.policies.map((p) => p.name);
  const missing = !r.aggregates[names[0]]?.clean_energy_pct;
  const best = (m: (typeof KEY_METRICS)[number]) => {
    const vals = names.map((n) => r.aggregates[n][m.key]?.mean).filter((v) => v !== undefined) as number[];
    return vals.length ? (m.better === "low" ? Math.min(...vals) : Math.max(...vals)) : null;
  };
  const text = conclusion(r);
  return (
    <Panel title="Do the carbon-aware policies help?" sub={`Simulated results · mean of ${r.runs.length / names.length} runs per policy on identical workloads. Green marks the best value in each column.`}>
      {missing && <p className="mb-3 text-[13px] text-warn">This run was saved before clean-energy usage was measured. Run a new experiment to see it.</p>}
      <div className="overflow-x-auto">
        <table className="data-table w-full min-w-[640px] tabular-nums">
          <thead>
            <tr><th>Policy</th>{KEY_METRICS.map((m) => <th key={m.key} className="!text-right" title={m.help}>{m.label}<div className="text-[11px] font-normal normal-case text-faint">{m.help}</div></th>)}</tr>
          </thead>
          <tbody>
            {names.map((n) => (
              <tr key={n}>
                <td className="font-medium"><span className="mr-2 inline-block h-2.5 w-2.5 rounded-full" style={{ background: POLICY_COLORS[n] }} />{POLICY_SHORT[n]}</td>
                {KEY_METRICS.map((m) => {
                  const v = r.aggregates[n][m.key]?.mean;
                  const isBest = v !== undefined && v === best(m) && names.length > 1;
                  return <td key={m.key} className={`text-right text-[15px] ${isBest ? "font-semibold text-ok" : ""}`}>{v === undefined ? "—" : m.fmt(v)}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="mt-4 space-y-1 text-[13px] text-muted">
        <li><span className="font-medium text-ink-2">FIFO</span> ignores carbon. <span className="font-medium text-ink-2">Threshold</span> waits while electricity is above {num(threshold)} gCO₂e/kWh. <span className="font-medium text-ink-2">Debt controller</span> also tracks and repays carbon debt. <span className="font-medium text-ink-2">Predictive</span> does that and uses the forecast to plan.</li>
        <li>No policy is best at everything: waiting for clean electricity lowers carbon but can cost deadlines.</li>
      </ul>
      {text && <p className="mt-4 rounded-2xl border border-line bg-subtle px-4 py-3 text-[14px] leading-relaxed text-ink">{text}</p>}
    </Panel>
  );
}

function Results({ exp }: { exp: Experiment }) {
  return (
    <div className="flex flex-col gap-8">
      <KeyResults r={exp.results!} threshold={Number(exp.config.debt_intensity_threshold ?? 350)} />
      <Details summary="Advanced details (all metrics, charts, method)">
        <AdvancedResults exp={exp} />
      </Details>
    </div>
  );
}

function AdvancedResults({ exp }: { exp: Experiment }) {
  const r = exp.results!;
  const [metric, setMetric] = useState("gross_emissions_g");
  const label = r.metric_labels[metric];
  const barData = r.policies.map((p) => ({ policy: p.name, mean: r.aggregates[p.name][metric].mean, std: r.aggregates[p.name][metric].std }));
  const series = useMemo(() => {
    const rows: Record<number, Record<string, number>> = {};
    for (const [policy, pts] of Object.entries(r.timeseries)) {
      for (const p of pts) (rows[p.slot] ??= { slot: p.slot })[policy] = p.effective_debt_g;
    }
    return Object.values(rows).sort((a, b) => a.slot - b.slot);
  }, [r]);
  return (
    <div className="flex flex-col gap-8">
      <Panel title="What the run shows" sub={`${exp.config.seeds.length} seeds × ${r.policies.length} policies, ${r.trace_summary.jobs} jobs per trace, completed in ${num((exp.duration_ms ?? 0) / 1000, 1)} s.`}
        actions={<>
          <a className="link-button !h-8 !px-3 !text-[14px]" href={downloadUrl(`/api/experiments/${exp.id}/export.csv`)}><Download className="h-3.5 w-3.5" aria-hidden />CSV</a>
          <a className="link-button !h-8 !px-3 !text-[14px]" href={downloadUrl(`/api/experiments/${exp.id}/report.json`)}><Download className="h-3.5 w-3.5" aria-hidden />JSON report</a>
        </>}>
        <Summary r={r} />
      </Panel>

      <div className="grid gap-8 xl:grid-cols-2">
        <Panel title={label.label} sub={`Mean across seeds (${label.unit}); whiskers show ±1 standard deviation.`}
          actions={<select className="input w-auto" value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="Metric">
            {CHART_METRICS.map((m) => <option key={m} value={m}>{r.metric_labels[m].label}</option>)}
          </select>}>
          <div className="h-[260px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={barData} margin={{ top: 16, right: 8, bottom: 0, left: 0 }} barCategoryGap="28%">
                <CartesianGrid vertical={false} />
                <XAxis dataKey="policy" interval={0} tickFormatter={(p) => POLICY_SHORT[p]} tickLine={false} axisLine={{ stroke: "var(--line-strong)" }} />
                <YAxis tickLine={false} axisLine={false} width={56} />
                <Tooltip cursor={{ fill: "var(--raised)" }} content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const d = payload[0].payload as (typeof barData)[number];
                  return <div className="rounded-xl border border-line bg-surface px-3 py-2 text-[14px] shadow-lg">
                    <div className="font-medium">{POLICY_SHORT[d.policy]}</div>
                    <div className="tabular text-ink-2">{fmtMetric(metric, d.mean)} ± {num(d.std, 1)}</div>
                  </div>;
                }} />
                <Bar dataKey="mean" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                  {barData.map((d) => <Cell key={d.policy} fill={POLICY_COLORS[d.policy]} />)}
                  <ErrorBar dataKey="std" width={6} stroke="var(--ink-2)" strokeWidth={1.2} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <Panel title="Debt trajectory" sub={`Effective debt over the replay for seed ${r.timeseries_seed}.`}>
          <div className="h-[230px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="slot" type="number" domain={["dataMin", "dataMax"]} tickFormatter={slotClock} tickLine={false} axisLine={{ stroke: "var(--line-strong)" }} ticks={[0, 24, 48, 72, 96, 120, 144, 168, 192]} />
                <YAxis tickLine={false} axisLine={false} width={56} />
                <Tooltip content={({ active, payload, label: l }) => {
                  if (!active || !payload?.length) return null;
                  return <div className="rounded-xl border border-line bg-surface px-3 py-2 text-[14px] shadow-lg">
                    <div className="font-medium">{slotClock(Number(l))}</div>
                    {payload.map((p) => <div key={String(p.dataKey)} className="tabular text-ink-2">{POLICY_SHORT[String(p.dataKey)]}: {grams(Number(p.value))}</div>)}
                  </div>;
                }} />
                {r.policies.map((p) => (
                  <Line key={p.name} dataKey={p.name} stroke={POLICY_COLORS[p.name]} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2"><ChartLegend items={r.policies.map((p) => ({ label: POLICY_SHORT[p.name], color: POLICY_COLORS[p.name] }))} /></div>
        </Panel>
      </div>

      <Panel title="All metrics" sub={`Mean ± standard deviation; change is relative to ${POLICY_SHORT[r.reference_policy]}.`} bodyClass="p-0">
        <div className="overflow-x-auto">
          <table className="data-table w-full min-w-[820px] tabular">
            <thead><tr><th>Metric</th>{r.policies.map((p) => <th key={p.name} className="text-right"><span className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ background: POLICY_COLORS[p.name] }} />{POLICY_SHORT[p.name]}</th>)}</tr></thead>
            <tbody>
              {Object.keys(r.metric_labels).map((k) => (
                <tr key={k}>
                  <td><div>{r.metric_labels[k].label}</div><div className="text-[13px] text-muted">{r.metric_labels[k].unit}</div></td>
                  {r.policies.map((p) => {
                    const a = r.aggregates[p.name][k];
                    const pct = r.comparisons_vs_reference_pct[p.name][k];
                    return (
                      <td key={p.name} className="text-right">
                        <div>{num(a.mean, 1)} <span className="text-muted">± {num(a.std, 1)}</span></div>
                        {p.name !== r.reference_policy && pct !== null && <div className="text-[13px] text-muted">{pct > 0 ? "+" : ""}{num(pct, 1)}%</div>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {r.sweep && (
        <Panel title={`Sweep: ${SWEEP_PARAMS[r.sweep.param] ?? r.sweep.param}`} sub={`${POLICY_SHORT[r.sweep.policy]}, mean across seeds at each value.`}>
          <div className="grid gap-8 md:grid-cols-3">
            {["gross_emissions_g", "final_debt_g", "deadline_misses"].map((k) => (
              <div key={k}>
                <div className="mb-1 text-[14px] text-ink-2">{r.metric_labels[k].label}</div>
                <div className="h-[170px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={r.sweep!.points.map((p) => ({ value: p.value, y: p.aggregates[k].mean }))} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                      <CartesianGrid vertical={false} />
                      <XAxis dataKey="value" tickLine={false} axisLine={{ stroke: "var(--line-strong)" }} />
                      <YAxis tickLine={false} axisLine={false} width={52} />
                      <Tooltip formatter={(v: number) => fmtMetric(k, v)} labelFormatter={(l) => `${r.sweep!.param} = ${l}`}
                        contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 13.5, boxShadow: "var(--shadow-lg)" }} />
                      <Line dataKey="y" name={r.metric_labels[k].label} stroke={POLICY_COLORS[r.sweep!.policy]} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <Panel title="Method and assumptions">
        <ul className="list-disc space-y-1 pl-5 text-[14px] text-ink-2">
          {r.methodology.map((m) => <li key={m}>{m}</li>)}
          <li>Trace for seed {r.trace_summary.seed}: {Object.entries(r.trace_summary.by_class).map(([c, n]) => `${n} ${c}`).join(", ")} jobs, {num(r.trace_summary.estimated_energy_kwh, 1)} kWh at full speed.</li>
          <li>Host: {r.environment.platform}, Python {r.environment.python}.</li>
        </ul>
      </Panel>
    </div>
  );
}

function ConfigPanel({ onStarted }: { onStarted: (id: string) => void }) {
  const toast = useToast();
  const [defaults, setDefaults] = useState<Record<string, any> | null>(null);
  const [form, setForm] = useState<Record<string, any>>({});
  const [seedsText, setSeedsText] = useState("1, 2, 3, 4, 5");
  const [sweepText, setSweepText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.experimentDefaults().then((d) => { setDefaults(d); setForm(d); }).catch((e) => setErr(e.message));
  }, []);
  if (!defaults) return <Panel title="Run an experiment">{err ? <ErrorNote message={err} /> : <Loading />}</Panel>;
  const set = (k: string, v: unknown) => setForm((f) => ({ ...f, [k]: v }));
  const togglePolicy = (p: PolicyName) =>
    set("policies", form.policies.includes(p) ? form.policies.filter((x: string) => x !== p) : ALL_POLICIES.filter((x) => x === p || form.policies.includes(x)));
  const submit = async () => {
    setErr(null);
    const seeds = seedsText.split(/[,\s]+/).filter(Boolean).map(Number);
    if (seeds.some((s) => !Number.isInteger(s) || s < 0)) return setErr("Seeds must be non-negative whole numbers separated by commas.");
    const sweep_values = sweepText.split(/[,\s]+/).filter(Boolean).map(Number);
    if (form.sweep_param && (!sweep_values.length || sweep_values.some((v) => !Number.isFinite(v)))) return setErr("Enter numeric sweep values, for example 150, 200, 250.");
    setBusy(true);
    try {
      const exp = await api.runExperiment({ ...form, seeds, sweep_param: form.sweep_param || null, sweep_values: form.sweep_param ? sweep_values : [] });
      toast("info", `Experiment “${exp.name}” queued.`);
      onStarted(exp.id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const field = (k: string, label: string, step = 1) => (
    <div>
      <label className="label" htmlFor={`e-${k}`}>{label}</label>
      <input id={`e-${k}`} type="number" step={step} className="input tabular" value={form[k]} onChange={(e) => set(k, e.target.value === "" ? "" : Number(e.target.value))} />
    </div>
  );
  return (
    <Panel title="Run an experiment" sub="Every policy replays the same seeded trace and carbon curve."
      actions={<Button size="sm" variant="primary" onClick={submit} busy={busy} disabled={!form.policies?.length}>Run experiment</Button>}>
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="e-name">Name</label>
            <input id="e-name" className="input" value={form.name} onChange={(e) => set("name", e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="e-seeds">Seeds</label>
            <input id="e-seeds" className="input tabular" value={seedsText} onChange={(e) => setSeedsText(e.target.value)} />
          </div>
        </div>
        <fieldset>
          <legend className="label">Policies</legend>
          <div className="flex flex-wrap gap-3">
            {ALL_POLICIES.map((p) => (
              <label key={p} className="flex items-center gap-2 text-[14px] text-ink-2">
                <input type="checkbox" className="accent-[var(--violet)]" checked={form.policies.includes(p)} onChange={() => togglePolicy(p)} />
                <span className="h-2 w-2 rounded-full" style={{ background: POLICY_COLORS[p] }} aria-hidden />{POLICY_SHORT[p]}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="grid grid-cols-3 gap-3">
          {field("emergency", "Emergency jobs")}
          {field("normal", "Normal jobs")}
          {field("background", "Background jobs")}
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="label" htmlFor="e-profile">Grid profile</label>
            <select id="e-profile" className="input" value={form.profile} onChange={(e) => set("profile", e.target.value)}>
              <option value="solar_midday">Solar midday</option><option value="windy_night">Windy night</option><option value="dirty_flat">Dirty flat</option>
            </select>
          </div>
          {field("debt_intensity_threshold", "Debt threshold", 10)}
          {field("green_threshold", "Green threshold", 10)}
        </div>
        <div className="grid grid-cols-3 gap-3">
          {field("debt_soft_g", "Soft band (g)", 10)}
          {field("debt_hard_g", "Hard band (g)", 10)}
          {field("debt_critical_g", "Critical band (g)", 10)}
        </div>
        <div className="grid grid-cols-[1fr_1fr] gap-3 border-t border-line pt-4">
          <div>
            <label className="label" htmlFor="e-sweep">Parameter sweep (optional)</label>
            <select id="e-sweep" className="input" value={form.sweep_param ?? ""} onChange={(e) => set("sweep_param", e.target.value || null)}>
              <option value="">No sweep</option>
              {Object.entries(SWEEP_PARAMS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="e-sweepv">Values</label>
            <input id="e-sweepv" className="input tabular" placeholder="150, 200, 250" disabled={!form.sweep_param} value={sweepText} onChange={(e) => setSweepText(e.target.value)} />
          </div>
        </div>
        {err && <ErrorNote message={err} />}
      </div>
    </Panel>
  );
}

export default function Experiments() {
  const { version } = useApp();
  const toast = useToast();
  const [selected, setSelected] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [tab, setTab] = useState<"results" | "new" | "runs">("results");
  const list = usePoll(api.experiments, 2500, [version]);
  const running = list.data?.some((e) => e.status === "running" || e.status === "queued");
  const current = usePoll(() => (selected ? api.experiment(selected) : Promise.resolve(null)), running ? 800 : 0, [selected, running]);
  useEffect(() => {
    if (!selected && list.data?.length) setSelected(list.data.find((e) => e.status === "completed")?.id ?? list.data[0].id);
  }, [list.data, selected]);

  const remove = async () => {
    if (!deleting) return;
    try {
      await api.deleteExperiment(deleting);
      toast("success", "Experiment deleted.");
      if (selected === deleting) setSelected(null);
      list.refresh();
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setDeleting(null);
    }
  };

  const exp = current.data;
  const runs = list.data ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="Experiments · simulated" title="Does the scheduler help?"
        description="The same simulated workloads and grid are replayed under each of the four policies, so the comparison is fair. Results are calculated, not tuned, and always use simulated inputs."
        actions={<Button variant="primary" onClick={() => setTab("new")}>New experiment</Button>}
      />
      <Tabs value={tab} onChange={setTab} tabs={[
        { value: "results", label: "Results" },
        { value: "new", label: "New experiment" },
        { value: "runs", label: "Saved runs", count: runs.length },
      ]} />
      <TabPanel id={tab}>
        {tab === "new" && <ConfigPanel onStarted={(id) => { setSelected(id); setTab("results"); list.refresh(); }} />}

        {tab === "runs" && (
          <Panel title="Saved runs" sub="Choose a run to see its results.">
            {list.error ? <ErrorNote message={list.error} /> : !list.data ? <Loading /> : runs.length === 0 ? (
              <EmptyState title="No experiments yet" body="Start one from the New experiment tab. Five seeds take about a second." />
            ) : (
              <ul data-lenis-prevent className="scroll-area flex max-h-[600px] flex-col gap-1.5">
                {runs.map((e) => (
                  <li key={e.id}>
                    <div className={`flex items-center gap-3 rounded-2xl px-4 py-3.5 transition-colors ${selected === e.id ? "bg-raised" : "hover:bg-raised"}`}>
                      <button className="min-w-0 flex-1 text-left" onClick={() => { setSelected(e.id); setTab("results"); }}>
                        <div className="truncate text-[15.5px] font-medium">{e.name}</div>
                        <div className="mt-0.5 text-[14px] text-muted">
                          {localTime(e.created_at)}, {e.status === "running" || e.status === "queued" ? `${e.status} ${Math.round(e.progress * 100)}%` : e.status}
                        </div>
                      </button>
                      {e.status !== "running" && e.status !== "queued" && (
                        <Button size="sm" variant="ghost" aria-label={`Delete ${e.name}`} onClick={() => setDeleting(e.id)} icon={<Trash2 className="h-4 w-4" />} />
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        )}

        {tab === "results" && (
          <div className="flex flex-col gap-8">
            {runs.length > 0 && (
              <div className="flex flex-wrap items-center gap-3">
                <label htmlFor="run-pick" className="text-[14.5px] text-muted">Showing</label>
                <select id="run-pick" className="input w-auto min-w-[280px]" value={selected ?? ""} onChange={(e) => setSelected(e.target.value)}>
                  {runs.map((r) => <option key={r.id} value={r.id}>{r.name} ({localTime(r.created_at)})</option>)}
                </select>
              </div>
            )}
            {!exp && runs.length === 0 && (
              <EmptyState title="No results yet" body="Run the default comparison to see the four policies side by side."
                action={<Button variant="primary" onClick={() => setTab("new")}>New experiment</Button>} />
            )}
            {exp && (exp.status === "running" || exp.status === "queued") && (
              <Panel title={`Running “${exp.name}”`}>
                <div className="h-2.5 overflow-hidden rounded-full bg-raised" role="progressbar" aria-valuenow={Math.round(exp.progress * 100)} aria-valuemin={0} aria-valuemax={100}>
                  <motion.div className="h-full rounded-full bg-ink" animate={{ width: `${exp.progress * 100}%` }} transition={{ duration: 0.4 }} />
                </div>
                <p className="mt-3 text-[14.5px] text-muted">{Math.round(exp.progress * 100)}% of the replays are done.</p>
              </Panel>
            )}
            {exp?.status === "failed" && <ErrorNote message={`Experiment failed: ${exp.error}`} />}
            {exp?.status === "completed" && exp.results && <Results exp={exp} />}
          </div>
        )}
      </TabPanel>
      <ConfirmDialog open={!!deleting} title="Delete this experiment?" body="Its saved configuration and results are removed. Exported files are not affected."
        confirmLabel="Delete experiment" danger onCancel={() => setDeleting(null)} onConfirm={remove} />
    </div>
  );
}