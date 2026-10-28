import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useApp, usePollInterval } from "../lib/appState";
import { ACTION_LABELS, STATE_LABELS, gramsAuto, num, simClock, slotClock } from "../lib/format";
import { usePoll } from "../lib/hooks";
import type { ControllerSettings, ControllerView } from "../lib/types";
import { DebtChart } from "../components/charts";
import { Button, ClassBadge, Details, EmptyState, ErrorNote, Loading, PageHeader, Panel, Segmented, Stat, TabPanel, Tabs, useToast } from "../components/ui";

function DebtBands({ view }: { view: ControllerView }) {
  const s = view.settings;
  const soft = Number(s.debt_soft_g), hard = Number(s.debt_hard_g), crit = Number(s.debt_critical_g);
  const max = Math.max(crit * 1.25, view.effective_debt_g * 1.1, 100);
  const pos = (v: number) => `${Math.min(100, (v / max) * 100)}%`;
  const bands = [
    { from: 0, to: soft, label: "Repaying", color: "var(--violet-soft)" },
    { from: soft, to: hard, label: "Soft throttle", color: "var(--warn-soft)" },
    { from: hard, to: crit, label: "Hard throttle", color: "var(--warn-band)" },
    { from: crit, to: max, label: "Critical", color: "var(--danger-soft)" },
  ];
  return (
    <div>
      <div className="relative h-9 overflow-hidden rounded-control border border-line">
        {bands.map((b) => (
          <div key={b.label} className="absolute inset-y-0 flex items-center px-2 text-[13px] text-ink-2"
            style={{ left: pos(b.from), width: `calc(${pos(b.to)} - ${pos(b.from)})`, background: b.color }}>
            <span className="truncate">{b.label}</span>
          </div>
        ))}
        <div className="absolute inset-y-0 w-0.5 bg-violet" style={{ left: pos(view.effective_debt_g) }} aria-hidden />
      </div>
      <div className="relative mt-1 h-4 text-[12.5px] text-muted tabular">
        {[soft, hard, crit].map((v) => <span key={v} className="absolute -translate-x-1/2" style={{ left: pos(v) }}>{num(v)} g</span>)}
      </div>
      <table className="data-table mt-3 w-full tabular">
        <thead><tr><th>Band</th><th>Normal jobs</th><th>Background jobs</th></tr></thead>
        <tbody>
          {Object.entries(view.throttle_table).map(([band, row]) => (
            <tr key={band} className={Number(band) === view.band ? "bg-violet-soft" : ""}>
              <td>{STATE_LABELS[view.band_names[band]] ?? view.band_names[band]}{Number(band) === view.band && <span className="ml-2 text-[13.5px] text-violet">current</span>}</td>
              <td>{Math.round(row.normal * 100)}%</td>
              <td>{row.background === 0 ? "Paused" : `${Math.round(row.background * 100)}%`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[13.5px] text-muted">
        Applied only outside green windows, never to emergencies, and only when the job can still finish two slots before its deadline.
        Throttling is a scheduler-level capacity share, not OS-level CPU throttling, and it raises energy per unit of work.
      </p>
    </div>
  );
}

type Draft = ControllerSettings;

function SettingsForm({ view }: { view: ControllerView }) {
  const { bump, mode } = useApp();
  const live = mode === "live";
  const toast = useToast();
  const [draft, setDraft] = useState<Draft>(view.settings);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setDraft(view.settings), [view.settings]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(view.settings);
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const patch: Record<string, unknown> = {};
      for (const k of Object.keys(draft) as (keyof Draft)[]) {
        if (JSON.stringify(draft[k]) !== JSON.stringify(view.settings[k])) patch[k] = draft[k];
      }
      await api.updateSettings(patch);
      toast("success", "Settings saved. The controller uses them from the next slot.");
      bump();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const field = (k: keyof Draft, label: string, help: string, step = 1) => (
    <div>
      <label className="label" htmlFor={`s-${k}`}>{label}</label>
      <input id={`s-${k}`} type="number" step={step} className="input tabular-nums" value={String(draft[k])}
        onChange={(e) => set(k, (typeof view.settings[k] === "number" ? Number(e.target.value) : e.target.value) as never)} />
      <p className="mt-1.5 text-[12px] leading-snug text-faint">{help}</p>
    </div>
  );
  return (
    <Panel title={`Settings (${live ? "Live" : "Simulation"} mode)`} sub="Each mode keeps its own settings. Changes apply from the next step."
      actions={<>
        {dirty && <Button size="sm" variant="ghost" onClick={() => setDraft(view.settings)}>Discard</Button>}
        <Button size="sm" variant="primary" disabled={!dirty} busy={busy} onClick={save}>Save settings</Button>
      </>}>
      <div className="flex flex-col gap-5">
        <div>
          <label className="label" htmlFor="s-policy">Scheduling policy</label>
          <select id="s-policy" className="input" value={draft.policy} onChange={(e) => set("policy", e.target.value as Draft["policy"])}>
            {view.policies.map((p) => <option key={p.name} value={p.name}>{p.label}</option>)}
          </select>
          <p className="mt-1.5 text-[12px] text-faint">FIFO ignores carbon. Threshold waits while the grid is above the debt threshold. The debt controller also tracks and repays carbon debt. Predictive does that and uses the forecast to pick a cleaner time.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          {field("debt_intensity_threshold", "Carbon debt threshold (gCO₂e/kWh)", "Running above this intensity creates carbon debt.", 10)}
          {field("green_threshold", "Clean-electricity level (gCO₂e/kWh)", "At or below this the grid counts as clean; debt repayment runs here.", 10)}
        </div>
        <details className="rounded-2xl border border-line px-4 py-3">
        <summary className="cursor-pointer text-[13.5px] font-semibold text-ink-2">Advanced settings</summary>
        <div className="mt-4 flex flex-col gap-5">
        <div className="grid gap-4 sm:grid-cols-3">
          {field("debt_soft_g", "Soft band (g)", "Above this: background work at 50%.", 10)}
          {field("debt_hard_g", "Hard band (g)", "Above this: normal 50%, background 20%.", 10)}
          {field("debt_critical_g", "Critical band (g)", "Above this: normal 20%, background paused.", 10)}
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          {field("workers", "Workers", "How many jobs can run at once.")}
          {field("emergency_reserve", "Emergency reserve", "Workers kept free for emergencies.")}
          {field("static_power_fraction", "Static power share", "Power drawn even when throttled (simulation energy model).", 0.05)}
        </div>
        <label className="flex items-start gap-2.5 text-[13.5px] text-ink-2">
          <input type="checkbox" className="mt-0.5" checked={draft.proactive_throttling} onChange={(e) => set("proactive_throttling", e.target.checked)} />
          <span>Proactive throttling<span className="block text-[12px] text-faint">Throttle one band early when the forecast shows the debt cannot be repaid in time.</span></span>
        </label>
        <div className="rounded-2xl border border-line bg-subtle px-4 py-3 text-[12.5px] text-muted">
          Deadline rules (always on): a job is never deferred or throttled so far that it would miss its deadline; a 2-slot safety margin is kept; emergencies are never throttled.
        </div>
        {!live && (
          <div className="border-t border-line pt-5">
            <div className="mb-3 text-[13.5px] font-semibold text-ink-2">Simulated grid</div>
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="sm:col-span-3">
                <label className="label" htmlFor="s-profile">Profile</label>
                <select id="s-profile" className="input" value={draft.profile} onChange={(e) => set("profile", e.target.value)}>
                  {Object.keys(view.profiles).map((p) => <option key={p} value={p}>{p.replace("_", " ")}</option>)}
                </select>
                <p className="mt-1.5 text-[12px] text-faint">{view.profiles[draft.profile]}</p>
              </div>
              {field("seed", "Seed", "Same seed, same curve: repeatable runs.")}
              {field("noise_pct", "Noise (%)", "Random variation around the profile.", 0.5)}
            </div>
            <p className="mt-1.5 text-[12px] text-faint">To switch the grid to green or coal-heavy, use the buttons on the Overview page.</p>
          </div>
        )}
        </div>
        </details>
        {live && (
          <p className="text-[12.5px] text-faint">In Live mode the grid curve is the real India Energy Atlas reading (and forecast when available); it cannot be edited.</p>
        )}
        {err && <ErrorNote message={err} />}
      </div>
    </Panel>
  );
}


type Tab = "projection" | "jobs" | "throttle" | "decisions";

const BAND_PLAIN: Record<string, string> = {
  NORMAL: "No carbon debt",
  REPAYING: "Repaying a small debt",
  THROTTLE_SOFT: "Debt is building: flexible work slowed to 50%",
  THROTTLE_HARD: "High debt: normal work 50%, flexible work 20%",
  CRITICAL: "Very high debt: flexible work paused",
  CARBON_UNAWARE: "This policy ignores carbon",
  THRESHOLD: "Threshold rule (no debt tracking)",
};

export default function Controller({ onOpenJob }: { onOpenJob: (id: string) => void }) {
  const { version, state } = useApp();
  const interval = usePollInterval();
  const { data: view, error, refresh } = usePoll(api.controller, interval, [version]);
  const decisions = usePoll(() => api.decisions(80), interval, [version]);
  const timeline = usePoll(api.timeline, interval, [version]);
  const [placementFilter, setPlacementFilter] = useState<"all" | "deferred">("all");
  const [tab, setTab] = useState<Tab>("projection");

  const projWindow = useMemo<[number, number]>(() => {
    if (!view) return [0, 96];
    const start = Math.max(0, view.plan.slot - 32);
    return [start, Math.max(start + 64, Math.min(view.plan.horizon_end_slot, view.plan.slot + 64))];
  }, [view]);

  if (error && !view) return <ErrorNote message={error} onRetry={refresh} />;
  if (!view) return <Loading />;
  const plan = view.plan;
  const placements = placementFilter === "all" ? plan.placements : plan.placements.filter((p) => p.start_slot !== null && p.start_slot > plan.slot);
  const s = view.settings;
  const policyLabel = view.policies.find((p) => p.name === s.policy)?.label ?? s.policy;

  return (
    <div>
      <PageHeader
        eyebrow="Scheduler" title="How the scheduler decides."
        description={view.effective_debt_g > 0
          ? "Carbon debt is outstanding, so flexible work is held for clean periods until it is repaid."
          : "No carbon debt is outstanding. Flexible work runs when electricity is clean enough, or when its deadline requires it."}
      />
      <div className="mb-8 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Carbon debt threshold" value={<>{num(Number(s.debt_intensity_threshold))}<span className="ml-1.5 text-[14px] font-normal text-muted">g/kWh</span></>}
          hint="Running above this adds carbon debt" />
        <Stat label="Clean-electricity level" tone="clean" value={<>{num(Number(s.green_threshold))}<span className="ml-1.5 text-[14px] font-normal text-muted">g/kWh</span></>}
          hint="At or below this, electricity counts as clean" />
        <Stat label="Carbon debt now" tone={view.effective_debt_g > 0 ? "violet" : "ink"} value={gramsAuto(view.effective_debt_g)}
          hint={view.effective_debt_g <= 0 && !["CARBON_UNAWARE", "THRESHOLD"].includes(view.state) ? "No carbon debt" : BAND_PLAIN[view.state] ?? view.state} />
        <Stat label="Grid now" tone={view.green_now ? "clean" : "ink"} value={<>{num(view.current_intensity)}<span className="ml-1.5 text-[14px] font-normal text-muted">g/kWh</span></>}
          hint={view.green_now ? "Clean period" : "Not a clean period"} />
      </div>

      <div className="flex flex-col gap-8">
        <Panel title="The rules" sub={`Active policy: ${policyLabel}`}>
          <ol className="list-decimal space-y-1.5 pl-5 text-[14px] leading-relaxed text-ink-2">
            <li><span className="font-medium">Urgent</span> processes always run immediately. One worker is kept free for them.</li>
            <li>A process whose <span className="font-medium">deadline is close</span> runs now, even on carbon-intensive electricity.</li>
            <li><span className="font-medium">Flexible</span> processes wait for a cleaner period if one is expected before their deadline{s.policy === "debt_predictive" ? " (the predictive controller books that time in advance)" : ""}.</li>
            <li>While there is carbon debt, flexible work runs only in clean periods, and running flexible work may be slowed — never urgent work, and never past a deadline.</li>
            <li>When postponed work runs cleaner than it would have, the carbon saved repays the debt. Debt can never go below zero.</li>
          </ol>
          {s.policy === "fifo" && <p className="mt-3 text-[13px] text-warn">FIFO is selected: it ignores carbon (used as the comparison baseline).</p>}
        </Panel>

        <Panel title="Planned start times" sub="Where each waiting flexible process will run, and why."
          actions={<Segmented label="Placement filter" value={placementFilter} onChange={setPlacementFilter}
            options={[{ value: "all", label: "All" }, { value: "deferred", label: "Postponed only" }]} />}>
          {view.plan_is_advisory && <p className="mb-3 text-[13px] text-muted">The active policy does not plan ahead; this shows what the predictive controller would do.</p>}
          {placements.length === 0 ? (
            <p className="text-[15px] text-muted">No flexible processes are waiting.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-line">
              {placements.map((p) => (
                <li key={p.job_id} className="py-4 first:pt-0 last:pb-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <button className="text-[15px] font-medium hover:underline" onClick={() => onOpenJob(p.job_id)}>{p.name}</button>
                    <ClassBadge jobClass={p.job_class} />
                    <span className="text-[14px] font-medium text-ink">
                      {p.start_slot === null ? "Waiting for a free worker" : p.start_slot === plan.slot ? "Starts now" : `Starts ${slotClock(p.start_slot)}`}
                    </span>
                    {p.green && <span className="text-[13px] text-clean">clean period</span>}
                    {p.forced && <span className="text-[13px] text-warn">deadline protection</span>}
                  </div>
                  <div className="mt-1.5 text-[13.5px] text-muted tabular-nums">
                    {num(p.now_avg)} → {num(p.window_avg ?? p.now_avg)} gCO₂e/kWh · deadline {simClock(p.deadline_time, state?.clock.epoch)}
                    {p.est_credit_g > 0 && <span className="text-clean"> · could repay {gramsAuto(p.est_credit_g)}</span>}
                  </div>
                  <p className="mt-1 max-w-[90ch] text-[13px] leading-relaxed text-faint">{p.reason}</p>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <SettingsForm view={view} />

        <Details>
          <Tabs<Tab> value={tab} onChange={setTab} tabs={[
            { value: "projection", label: "Debt forecast" },
            { value: "jobs", label: "Repayment and running", count: view.repayment_queue.length + view.active_jobs.length },
            { value: "throttle", label: "Slow-down levels" },
            { value: "decisions", label: "Decision log" },
          ]} />
          <TabPanel id={tab}>
            {tab === "projection" && (
              <Panel title="Where carbon debt is heading" sub="Recomputed every step from the forecast and the waiting processes.">
                <div className="mb-6 grid grid-cols-2 gap-6 sm:grid-cols-4">
                  {[["Now", plan.start_debt_g], ["Projected peak", plan.peak_g], ["At end of plan", plan.end_balance_g], ["Repayable by plan", plan.repayable_g]].map(([k, v]) => (
                    <div key={k as string}>
                      <div className="text-[13px] text-muted">{k}</div>
                      <div className="mt-1 text-[22px] font-semibold tabular-nums">{gramsAuto(v as number)}</div>
                    </div>
                  ))}
                </div>
                <DebtChart points={timeline.data?.points ?? []} window={projWindow} projection={plan.projection} height={240} />
                <p className="mt-3 text-[13px] leading-relaxed text-muted">Solid: recorded debt. Dashed: projection from {slotClock(plan.slot)}. {plan.uncertainty_note}</p>
              </Panel>
            )}
            {tab === "jobs" && (
              <div className="grid gap-8 lg:grid-cols-2">
                <Panel title="Postponed processes" sub="The baseline is the grid intensity it would have run at, saved when it was postponed.">
                  {view.repayment_queue.length === 0 && view.repaid_jobs.length === 0 ? (
                    <EmptyState title="Nothing postponed yet" body="When a process is postponed, its baseline is saved here. It repays debt if it later runs cleaner and on time." />
                  ) : (
                    <table className="data-table w-full tabular">
                      <thead><tr><th>Process</th><th>Baseline</th><th>Runs</th><th>Repaid</th></tr></thead>
                      <tbody>
                        {[...view.repayment_queue, ...view.repaid_jobs].map((j) => (
                          <tr key={j.id}>
                            <td><button className="text-left font-medium hover:underline" onClick={() => onOpenJob(j.id)}>{j.name}</button><div className="text-[13px] text-muted">{j.status_label}</div></td>
                            <td>{num(j.baseline_intensity)}</td>
                            <td>{simClock(j.start_time ?? j.planned_start_time, state?.clock.epoch)}</td>
                            <td className="text-clean">{j.credit_earned_g > 0 ? gramsAuto(j.credit_g) : <span className="text-muted">pending</span>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </Panel>
                <Panel title="Running now" sub="Current speed of each running process.">
                  {view.active_jobs.length === 0 ? <p className="text-[15px] text-muted">Nothing is running.</p> : (
                    <ul className="flex flex-col divide-y divide-line">
                      {view.active_jobs.map((j) => (
                        <li key={j.id} className="py-3 first:pt-0">
                          <div className="flex flex-wrap items-center gap-3">
                            <button className="text-[15px] font-medium hover:underline" onClick={() => onOpenJob(j.id)}>{j.name}</button>
                            <span className={`text-[14px] font-medium tabular ${j.capacity < 1 ? "text-warn" : "text-ink-2"}`}>{j.state === "paused" ? "Paused" : `${Math.round(j.capacity * 100)}%`}</span>
                          </div>
                          <p className="mt-1 text-[13.5px] leading-relaxed text-ink-2">{j.plain_reason}</p>
                        </li>
                      ))}
                    </ul>
                  )}
                </Panel>
              </div>
            )}
            {tab === "throttle" && <Panel title="Slow-down levels" sub="How much speed non-urgent work gets as carbon debt grows."><DebtBands view={view} /></Panel>}
            {tab === "decisions" && (
              <Panel title="Decision log" sub="The last 80 decisions, newest first." bodyClass="px-0 pb-2">
                {!decisions.data?.length ? <p className="px-7 pb-5 text-[15px] text-muted">No decisions recorded yet.</p> : (
                  <div data-lenis-prevent className="scroll-area max-h-[640px] overflow-x-auto">
                    <table className="data-table w-full min-w-[760px]">
                      <thead><tr><th>Time</th><th>Action</th><th>Process</th><th>Reason</th></tr></thead>
                      <tbody>
                        {decisions.data.map((d) => (
                          <tr key={d.id} className="row-hover">
                            <td className="tabular text-muted">{slotClock(d.slot)}</td>
                            <td className="whitespace-nowrap font-medium">{ACTION_LABELS[d.action] ?? d.action}</td>
                            <td className="font-mono text-[14px]">{d.job_id ?? "—"}</td>
                            <td className="text-ink-2">{d.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>
            )}
          </TabPanel>
        </Details>
      </div>
    </div>
  );
}
