import { useState } from "react";
import { api } from "../lib/api";
import { useApp, usePollInterval } from "../lib/appState";
import { gramsAuto, gridLevel, num, simClock } from "../lib/format";
import { usePoll } from "../lib/hooks";
import type { SystemState } from "../lib/types";
import { ChartLegend, DebtChart, IntensityChart, dayWindow } from "../components/charts";
import { IconPause, IconPlay, IconStep } from "../components/icons";
import { AddProcess, QueueTable } from "../components/ProcessQueue";
import { LiveProcesses } from "../components/LiveProcesses";
import { Button, ConfirmDialog, Details, EmptyState, ErrorNote, Loading, PageHeader, Panel, useToast } from "../components/ui";
import { ControlNote, LiveGridCard } from "./LiveMode";

function useAct() {
  const { bump } = useApp();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const act = async (key: string, fn: () => Promise<unknown>, success?: string) => {
    setBusy(key);
    try {
      await fn();
      if (success) toast("success", success);
      bump();
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };
  return { busy, act };
}

/** Simulated grid: current value, plain level, and one-click controls. */
function GridControl({ state }: { state: SystemState }) {
  const { busy, act } = useAct();
  const [custom, setCustom] = useState("450");
  const [hours, setHours] = useState(2);
  const c = state.carbon;
  const level = gridLevel(c.intensity, c.green_threshold, c.debt_threshold);
  const color = { clean: "text-ok", warn: "text-warn", danger: "text-bad", ink: "text-ink" }[level.tone];
  const manual = c.manual;
  const set = (preset: "green" | "coal" | "custom" | "normal", value?: number) =>
    act(preset, () => api.setGrid(preset, value, hours),
      preset === "normal" ? "Back to the normal daily pattern." : `Simulated grid set for the next ${hours === 72 ? "3 days" : `${hours} h`}.`);
  const customValue = Number(custom);
  const customOk = custom !== "" && Number.isFinite(customValue) && customValue >= 0 && customValue <= 2000;
  return (
    <Panel title="Electricity right now" sub="Simulated grid. Change it to see how the scheduler reacts.">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <div>
          <span className={`font-display text-[44px] font-light leading-none ${color}`}>{num(c.intensity)}</span>
          <span className="ml-2 text-[13px] text-muted">gCO₂e/kWh</span>
        </div>
        <div className="pb-1 text-[14px]">
          <div className={`font-semibold ${color}`}>{level.label}</div>
          <div className="text-[12.5px] text-muted">
            Simulated · {manual ? `set manually until ${manual.until_label ?? "the end"}, then the normal daily pattern` : "normal daily pattern"}
          </div>
        </div>
      </div>
      <p className="mt-3 text-[12.5px] text-faint">
        Clean ≤ {num(c.green_threshold)} · carbon debt starts above {num(c.debt_threshold)} gCO₂e/kWh.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button variant="secondary" className="!border-ok/40 !text-ok" busy={busy === "green"} onClick={() => set("green")}>Switch to Green Energy</Button>
        <Button variant="secondary" className="!border-bad/40 !text-bad" busy={busy === "coal"} onClick={() => set("coal")}>Switch to Coal-Heavy Energy</Button>
        {manual && <Button variant="ghost" busy={busy === "normal"} onClick={() => set("normal")}>Back to normal pattern</Button>}
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div>
          <label className="label" htmlFor="grid-custom">Set carbon intensity</label>
          <input id="grid-custom" type="number" min={0} max={2000} step={10} className="input w-32 tabular-nums" value={custom} onChange={(e) => setCustom(e.target.value)} />
        </div>
        <Button busy={busy === "custom"} disabled={!customOk} onClick={() => set("custom", customValue)}>Set</Button>
        <div className="ml-auto">
          <label className="label" htmlFor="grid-hours">For</label>
          <select id="grid-hours" className="input w-auto" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            <option value={1}>1 hour</option><option value={2}>2 hours</option><option value={4}>4 hours</option><option value={72}>the rest of the run</option>
          </select>
        </div>
      </div>
      <p className="mt-2 text-[12px] text-faint">Green = 120 and coal-heavy = 650 gCO₂e/kWh (simulated values). Slots already played keep the value they had.</p>
    </Panel>
  );
}

function DemoControls({ state }: { state: SystemState }) {
  const { busy, act } = useAct();
  const [adding, setAdding] = useState(false);
  const [confirm, setConfirm] = useState<"reset" | "scenario" | null>(null);
  const atHorizon = state.clock.slot >= state.clock.horizon_slot;
  return (
    <Panel title="Demo controls" sub={`Simulated time ${state.clock.label} UTC · each step = 15 minutes`}>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" busy={busy === "samples"} onClick={() => act("samples", api.loadSamples, "Four sample processes loaded at 06:00.")}>Load Sample Processes</Button>
        <Button onClick={() => setAdding(true)}>Add Process</Button>
        <Button icon={<IconStep className="h-4 w-4" />} busy={busy === "step"} disabled={state.clock.autoplay || atHorizon}
          onClick={() => act("step", () => api.advance(1))}>Step 15 min</Button>
        <Button icon={state.clock.autoplay ? <IconPause className="h-4 w-4" /> : <IconPlay className="h-4 w-4" />} busy={busy === "play"}
          disabled={!state.clock.autoplay && atHorizon} onClick={() => act("play", () => api.autoplay(!state.clock.autoplay))}>
          {state.clock.autoplay ? "Pause" : "Play"}
        </Button>
        <Button variant="ghost" onClick={() => setConfirm("reset")}>Reset Demo</Button>
      </div>
      <ol className="mt-4 list-decimal space-y-0.5 pl-5 text-[12.5px] text-muted">
        <li>Load Sample Processes → Switch to Coal-Heavy Energy → Step.</li>
        <li>The urgent process runs; flexible ones are scheduled for later.</li>
        <li>Switch to Green Energy → Step: flexible work runs and repays the debt.</li>
      </ol>
      <AddProcess open={adding} onClose={() => setAdding(false)} />
      <ConfirmDialog
        open={confirm !== null}
        title={confirm === "scenario" ? "Play the full automatic scenario?" : "Reset the demo?"}
        body={confirm === "scenario"
          ? "This clears the simulation, loads eight processes and plays 06:00 to 16:00 automatically (one step every 0.7 s), using the normal daily grid pattern."
          : "All simulated processes and carbon-debt history are deleted, the clock returns to 06:00 and the grid returns to its normal daily pattern. Experiments and Live data are kept."}
        confirmLabel={confirm === "scenario" ? "Reset and play" : "Reset"}
        danger={confirm === "reset"}
        busy={busy === "reset" || busy === "scenario"}
        onCancel={() => setConfirm(null)}
        onConfirm={() => confirm === "scenario"
          ? act("scenario", () => api.runScenario("animated", 700), "Scenario started.").then(() => setConfirm(null))
          : act("reset", api.reset, "Demo reset to 06:00.").then(() => setConfirm(null))}
      />
      <button className="mt-3 text-[12.5px] font-semibold text-lav-ink hover:underline" onClick={() => setConfirm("scenario")}>
        Or play the full automatic scenario (06:00–16:00)
      </button>
    </Panel>
  );
}

/** Carbon debt added / repaid / remaining, the formula, and how it changed over time. */
function DebtPanel({ state }: { state: SystemState }) {
  const interval = usePollInterval();
  const { version } = useApp();
  const timeline = usePoll(api.timeline, interval, [version]);
  const L = state.ledger;
  const accruing = Math.max(0, L.effective_g - L.balance_g);
  const added = L.total_debt_g + accruing;
  const live = state.mode === "live";
  const thr = num(state.carbon.debt_threshold);
  const window: [number, number] = live
    ? [Math.max(0, state.clock.slot - 120), state.clock.slot + 4]
    : dayWindow(state.clock.slot);
  return (
    <Panel title="Carbon debt" sub="The extra carbon from running work while the grid is above the threshold.">
      <div className="grid grid-cols-3 gap-4">
        {[["Carbon Debt Added", gramsAuto(added), "text-lav-ink"], ["Carbon Debt Repaid", gramsAuto(L.credits_applied_g), "text-ok"],
          ["Carbon Debt Remaining", gramsAuto(L.effective_g), "text-ink"]].map(([k, v, cls]) => (
          <div key={k}>
            <div className="text-[12px] font-semibold text-muted">{k}</div>
            <div className={`mt-1 font-display text-[30px] font-light leading-none tabular-nums ${cls}`}>{v}</div>
          </div>
        ))}
      </div>
      {accruing > 0 && <p className="mt-2 text-[12px] text-faint">{gramsAuto(accruing)} of this comes from processes still running; it is recorded in History when they finish.</p>}
      <div className="mt-4 rounded-2xl border border-line bg-subtle px-4 py-3 text-[13px] leading-relaxed text-ink-2">
        <div className="font-mono text-[12.5px]">Carbon debt = Energy used × max(0, Grid intensity − {thr})</div>
        <div className="mt-1 text-muted">Example: 1 kWh at 600 gCO₂e/kWh adds 1 × (600 − {thr}) = {num(600 - state.carbon.debt_threshold)} g of debt.</div>
        <div className="mt-1 text-muted">
          When a process that was postponed later runs on cleaner electricity, the carbon it avoided repays the debt.
          Repaying does <span className="font-semibold text-ink-2">not</span> erase emissions that already happened.
        </div>
      </div>
      <div className="mt-4">
        {(timeline.data?.points.length ?? 0) === 0
          ? <p className="text-[13px] text-muted">The debt chart fills in as the simulation runs.</p>
          : <DebtChart points={timeline.data!.points} window={window} height={140} />}
      </div>
    </Panel>
  );
}

function Queue({ onOpenJob }: { onOpenJob: (id: string) => void }) {
  const { version, state } = useApp();
  const interval = usePollInterval();
  const jobs = usePoll(() => api.jobs({}), interval, [version]);
  const live = state?.mode === "live";
  return (
    <Panel title="Process queue" sub="What each process is doing and why. Click a row for the full reason." bodyClass="p-0">
      {jobs.error ? <div className="p-6"><ErrorNote message={jobs.error} /></div> : !jobs.data ? <div className="px-6"><Loading /></div> :
        jobs.data.length === 0 ? (
          <div className="p-6"><EmptyState title="No processes yet" body={live ? "Add demo processes on the Process Queue page, then start monitoring." : "Press Load Sample Processes."} /></div>
        ) : <QueueTable jobs={jobs.data} onOpenJob={onOpenJob} />}
    </Panel>
  );
}

function LaptopProcesses() {
  const live = usePoll(api.liveStatus, 2500, []);
  if (live.error) return <ErrorNote message={live.error} />;
  if (!live.data) return <Loading />;
  return <LiveProcesses processes={live.data.telemetry.processes} refreshedAt={live.data.telemetry.refreshed_at} limit={15} />;
}

function IntensityPanel({ state }: { state: SystemState }) {
  const { version } = useApp();
  const live = state.mode === "live";
  const curve = usePoll(api.curve, live ? 15000 : 0, [version, state.carbon.intensity, state.carbon.manual?.until_slot]);
  return (
    <Panel title="Electricity over time" sub={live ? "Solid: real readings. Dashed: provider forecast, or the latest reading held." : "Green bands are clean periods. The dashed line after “now” is the forecast the scheduler plans with."}>
      {curve.error ? <ErrorNote message={curve.error} /> : !curve.data ? <Loading /> : curve.data.points.length === 0 ? (
        <p className="py-4 text-[13px] text-muted">No real grid reading yet — Unavailable.</p>
      ) : (
        <>
          <IntensityChart points={curve.data.points} current={state.clock.slot} height={190}
            window={live ? [Math.max(0, state.clock.slot - 120), state.clock.slot + 40] : dayWindow(state.clock.slot)}
            greenThreshold={state.carbon.green_threshold} debtThreshold={state.carbon.debt_threshold} />
          <div className="mt-2">
            <ChartLegend items={[{ label: "gCO₂e/kWh", color: "var(--ink)" }, { label: "Forecast", color: "var(--muted)", dashed: true },
              { label: "Clean period", color: "var(--clean)", band: true }, { label: `Debt threshold (${num(state.carbon.debt_threshold)})`, color: "var(--danger)", dashed: true }]} />
          </div>
        </>
      )}
    </Panel>
  );
}

export default function Overview({ onOpenJob }: { onOpenJob: (id: string) => void }) {
  const { state, error } = useApp();
  if (!state) return error ? <ErrorNote message={error} /> : <Loading label="Connecting to the backend" />;
  const live = state.mode === "live";

  if (live) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader eyebrow="Live mode" title="Real grid data, real laptop processes."
          description={state.clock.autoplay ? "Monitoring is on. Values come from India Energy Atlas and this laptop." : "Press Start monitoring (top right) to collect real data."} />
        <div className="grid gap-6 xl:grid-cols-2">
          {state.live && <LiveGridCard grid={state.live.grid} green={state.carbon.green_threshold} debt={state.carbon.debt_threshold} />}
          <DebtPanel state={state} />
        </div>
        <Queue onOpenJob={onOpenJob} />
        <LaptopProcesses />
        <ControlNote />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-6">
      <PageHeader eyebrow="Simulation mode" title="Run flexible work when electricity is cleaner."
        description="Urgent work runs immediately, even on coal-heavy power. The extra carbon becomes carbon debt. Flexible work is moved to cleaner periods, which repays the debt." />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <GridControl state={state} />
        <DemoControls state={state} />
      </div>
      <Queue onOpenJob={onOpenJob} />
      <div className="grid gap-6 xl:grid-cols-2">
        <DebtPanel state={state} />
        <IntensityPanel state={state} />
      </div>
      <Details summary="How the scheduler decides">
        <ol className="list-decimal space-y-1.5 pl-5 text-[13.5px] leading-relaxed text-ink-2">
          <li><span className="font-medium">Urgent</span> processes always run immediately, even on carbon-intensive electricity.</li>
          <li>A process whose <span className="font-medium">deadline is close</span> runs now. Deadlines always come before carbon.</li>
          <li><span className="font-medium">Flexible</span> processes wait for a cleaner period if one is expected before their deadline.</li>
          <li>While there is carbon debt, flexible work runs only in clean periods, and flexible work already running may be slowed down.</li>
          <li>When postponed work runs cleaner than it would have, the carbon saved repays the debt.</li>
        </ol>
        <p className="text-[12.5px] text-muted">Active policy: {state.controller.policy_label}. Change it on the Scheduler page. Simulated time {simClock(state.clock.sim_time)} UTC.</p>
      </Details>
    </div>
  );
}
