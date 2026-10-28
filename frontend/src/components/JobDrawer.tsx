import { useState } from "react";
import { Copy, Download } from "lucide-react";
import { api } from "../lib/api";
import { useApp } from "../lib/appState";
import { ACTION_LABELS, CLASS_LABELS, grams, gramsAuto, intensity, minutes, num, shortHash, simClock, slotClock } from "../lib/format";
import { usePoll } from "../lib/hooks";
import type { JobDetail, Receipt } from "../lib/types";
import { Button, ClassBadge, Details, Drawer, ErrorNote, KV, Loading, Segmented, StatusBadge, useToast } from "./ui";

type Tab = "receipt" | "decisions" | "history" | "executions" | "ledger";

const ENERGY_SOURCE: Record<string, string> = {
  ESTIMATED_MODEL: "estimated from the declared power (simulation model)",
  MEASURED_RAPL_ATTRIBUTED: "measured by the CPU energy meter, shared by CPU time",
  ESTIMATED_CPU_TIME: "estimated from measured CPU time (no energy meter)",
};

const STATE_CHANGE: Record<string, string> = {
  ARRIVED: "queued", START: "running", START_FORCED: "running (deadline-forced)", EMERGENCY_START: "running (emergency)",
  REPAYMENT_START: "running (repayment)", MANUAL_START: "running (operator)", DEFER: "deferred", OPERATOR_HOLD: "deferred (operator)",
  PAUSE: "paused", RESTORE: "running", THROTTLE: "running (throttled)", COMPLETED: "completed", FAILED: "failed",
  CANCELLED: "cancelled", DEADLINE_MISSED: "deadline missed",
};

const mins = (a: string, b: string) => (new Date(b).getTime() - new Date(a).getTime()) / 60000;

function elapsed(start: string | null, finish: string | null, now: string | null): string {
  if (!start) return "not started";
  const end = finish ?? now;
  return end ? minutes(Math.max(0, mins(start, end))) : "—";
}

function remaining(deadline: string, now: string | null, finish: string | null): string {
  if (finish) return mins(finish, deadline) >= 0 ? `finished ${minutes(mins(finish, deadline))} early` : "finished late";
  if (!now) return "—";
  const left = mins(now, deadline);
  return left >= 0 ? `${minutes(left)} left` : `${minutes(-left)} overdue`;
}

/** A plain-English explanation of what happened to the job and how its carbon was calculated. */
function Summary({ detail, threshold }: { detail: JobDetail; nowIso: string | null; threshold: number }) {
  const j = detail.job;
  const source = detail.executions[0]?.energy_source;
  const avg = j.energy_kwh > 0 ? j.emissions_g / j.energy_kwh : null;
  const story = {
    pending: "Not arrived yet.",
    queued: "Waiting for the scheduler's next decision.",
    deferred: j.planned_start_time ? `Deferred: planned to start at ${simClock(j.planned_start_time)}.` : "Deferred.",
    running: `Running at ${Math.round(j.capacity * 100)}% capacity.`,
    paused: "Paused to cut carbon while debt is high; it resumes before its deadline.",
    completed: `Finished ${j.deadline_missed ? "after" : "before"} its deadline.`,
    failed: "Failed; the energy it used is still accounted.",
    cancelled: "Cancelled.",
  }[j.state];
  return (
    <div className="rounded-2xl border border-line bg-subtle px-5 py-4 text-[13.5px] leading-relaxed">
      <p className="font-medium text-ink">{story}</p>
      {j.last_reason && <p className="mt-1 text-ink-2"><span className="text-muted">Why: </span>{j.last_reason}</p>}
      {j.energy_kwh > 0 && (
        <div className="mt-3 space-y-1 border-t border-line pt-3 text-ink-2">
          <p><span className="text-muted">Energy: </span>{num(j.energy_kwh, 6)} kWh, {ENERGY_SOURCE[source ?? ""] ?? "estimated"}.</p>
          <p><span className="text-muted">Emissions = energy × grid intensity = </span>{grams(j.emissions_g, 3)}
            {avg !== null && <> (average {num(avg)} gCO₂e/kWh)</>}.</p>
          <p><span className="text-muted">Debt = energy × (intensity − {num(threshold)}) when above it = </span>{grams(j.debt_g, 3)}.</p>
          {j.credit_earned_g > 0 && <p className="text-ok">Verified credit {grams(j.credit_earned_g, 3)} for waiting until the grid was cleaner ({grams(j.credit_g, 3)} applied to the debt).</p>}
        </div>
      )}
    </div>
  );
}

/** The plain answer to "why is this process doing this?", from the backend's last recorded decision. */
function WhyBox({ detail, nowIso, epoch, threshold }: { detail: JobDetail; nowIso: string | null; epoch?: string; threshold: number }) {
  const j = detail.job;
  const source = detail.executions[0]?.energy_source;
  const energyLabel = source === "MEASURED_RAPL_ATTRIBUTED" ? "estimated share of measured CPU energy"
    : source === "ESTIMATED_CPU_TIME" ? "estimated from CPU time" : "estimated from its power";
  return (
    <div className="rounded-2xl border border-lav-line bg-lav-soft/40 px-5 py-4">
      <div className="text-[12px] font-semibold uppercase tracking-wide text-lav-ink">Why this decision?</div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <StatusBadge label={j.status_label} />
        <span className="text-[15px] font-medium text-ink">{j.plain_reason}</span>
      </div>
      <dl className="mt-3 grid gap-x-8 sm:grid-cols-2">
        <div>
          <KV label="Type">{CLASS_LABELS[j.job_class]}</KV>
          <KV label="Priority">{j.priority} (1 = highest)</KV>
          <KV label="Grid at that decision">{j.decision_intensity === null ? "—" : `${num(j.decision_intensity)} gCO₂e/kWh`}</KV>
        </div>
        <div>
          <KV label="Deadline">{simClock(j.deadline_time, epoch)}{j.deadline_missed && <span className="ml-1 text-bad">missed</span>}</KV>
          <KV label="Time to deadline">{remaining(j.deadline_time, nowIso, j.finish_time)}</KV>
          <KV label="Progress">{Math.round(j.progress * 100)}%</KV>
        </div>
      </dl>
      {j.last_reason && <p className="mt-3 text-[13px] text-ink-2"><span className="text-muted">Scheduler's exact reason: </span>{j.last_reason}</p>}
      {j.energy_kwh > 0 && (
        <p className="mt-3 border-t border-line pt-3 text-[13px] text-ink-2">
          Energy {num(j.energy_kwh, j.energy_kwh < 0.01 ? 6 : 3)} kWh ({energyLabel}) · emissions {gramsAuto(j.emissions_g)} ·
          carbon debt added {gramsAuto(j.debt_g)} (above {num(threshold)} gCO₂e/kWh)
          {j.credit_g > 0 && <span className="text-ok"> · repaid {gramsAuto(j.credit_g)} by running cleaner</span>}
        </p>
      )}
    </div>
  );
}

function History({ detail }: { detail: JobDetail }) {
  const steps = detail.decisions.filter((d) => STATE_CHANGE[d.action]);
  if (!steps.length) return <p className="text-[13.5px] text-muted">No state changes yet.</p>;
  return (
    <ol className="relative space-y-3 border-l border-line-strong pl-5">
      {steps.map((d) => (
        <li key={d.id} className="relative">
          <span className="absolute -left-[25px] top-1.5 h-2.5 w-2.5 rounded-full bg-lav-ink" aria-hidden />
          <div className="text-[13.5px]"><span className="font-medium">{STATE_CHANGE[d.action]}</span>
            <span className="ml-2 tabular-nums text-muted">{slotClock(d.slot)}</span>
            {d.capacity !== null && d.capacity < 1 && <span className="ml-2 text-warn">{Math.round(d.capacity * 100)}%</span>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function ReceiptView({ receipt }: { receipt: Receipt }) {
  const toast = useToast();
  const json = JSON.stringify(receipt, null, 2);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(json);
      toast("success", "Receipt copied as JSON.");
    } catch {
      toast("error", "Clipboard is unavailable in this browser; use Download instead.");
    }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([json], { type: "application/json" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `${receipt.receipt_id}.json` });
    a.click();
    URL.revokeObjectURL(url);
  };
  const c = receipt.carbon;
  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-2">
        <Button size="sm" onClick={copy} icon={<Copy className="h-3.5 w-3.5" />}>Copy JSON</Button>
        <Button size="sm" onClick={download} icon={<Download className="h-3.5 w-3.5" />}>Download receipt</Button>
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        <dl>
          <h3 className="mb-1 text-[14px] font-medium text-ink-2">Carbon</h3>
          <KV label="Gross emissions">{grams(c.gross_emissions_g, 1)}</KV>
          <KV label="Policy debt">{grams(c.policy_debt_g, 1)}</KV>
          <KV label="Credit earned">{grams(c.credit_earned_g, 1)}</KV>
          <KV label="Credit applied">{grams(c.credit_applied_g, 1)}</KV>
          <KV label="Net balance impact" hint="debt − credit applied">{grams(c.net_policy_balance_impact_g, 1)}</KV>
        </dl>
        <dl>
          <h3 className="mb-1 text-[14px] font-medium text-ink-2">Energy and grid</h3>
          <KV label="Energy">{num(receipt.energy.kwh, 3)} kWh</KV>
          <KV label="Full-speed estimate">{num(receipt.energy.full_speed_estimate_kwh, 3)} kWh</KV>
          <KV label="Avg intensity">{intensity(receipt.grid.avg_intensity_g_per_kwh)}</KV>
          <KV label="Baseline intensity">{intensity(receipt.grid.baseline_intensity_g_per_kwh)}</KV>
          <KV label="Deadline">{receipt.deadline.met ? "Met" : "Missed"}</KV>
        </dl>
      </div>
      <div className="mt-4 space-y-2 text-[14px] text-ink-2">
        <p><span className="text-muted">Energy source: </span>{receipt.energy.source}</p>
        {receipt.scheduling.deferral_decision && <p><span className="text-muted">Deferral: </span>{receipt.scheduling.deferral_decision}</p>}
        {receipt.scheduling.start_decision && <p><span className="text-muted">Start: </span>{receipt.scheduling.start_decision}</p>}
        {receipt.scheduling.credit_void_reason && <p className="text-warn">Credit voided: {receipt.scheduling.credit_void_reason}</p>}
        <p><span className="text-muted">Real proxy-kernel CPU time: </span>{num(receipt.execution_evidence.proxy_kernel_cpu_ms, 1)} ms</p>
      </div>
      <h3 className="mt-5 mb-1 text-[14px] font-medium text-ink-2">Debt records</h3>
      <ul className="space-y-1 text-[14px]">
        {receipt.ledger.map((l: any) => (
          <li key={l.event_id} className="flex flex-wrap gap-x-3">
            <span className="font-mono text-ink-2">{l.event_id}</span>
            <span>{l.event_type}</span>
            <span className="tabular">{grams(l.amount_g, 3)}</span>
            <span className="font-mono text-muted" title={l.hash}>{shortHash(l.hash, 16)}</span>
          </li>
        ))}
      </ul>
      <h3 className="mt-5 mb-1 text-[14px] font-medium text-ink-2">Measurement limitations</h3>
      <ul className="list-disc space-y-1 pl-5 text-[14px] text-muted">
        {receipt.limitations.map((l: string) => <li key={l}>{l}</li>)}
      </ul>
    </div>
  );
}

export function JobDrawer({ jobId, onClose }: { jobId: string | null; onClose: () => void }) {
  const { version, state } = useApp();
  const [tab, setTab] = useState<Tab>("decisions");
  const { data, error, loading, refresh } = usePoll(
    () => (jobId ? api.job(jobId) : Promise.resolve(null)),
    state?.clock.autoplay ? 1200 : 0,
    [jobId, version],
  );
  const j = data?.job;
  const activeTab: Tab = tab === "receipt" && !data?.receipt ? "decisions" : tab;
  return (
    <Drawer
      open={!!jobId}
      onClose={onClose}
      title={
        j ? (
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[13.5px] text-muted">{j.id}</span>
              <ClassBadge jobClass={j.job_class} />
            </div>
            <h2 className="mt-1 font-display text-xl font-semibold tracking-[-0.01em]">{j.name}</h2>
          </div>
        ) : <span className="font-display text-lg">Job details</span>
      }
    >
      {loading && !data ? <Loading /> : error ? <ErrorNote message={error} onRetry={refresh} /> : j && data ? (
        <>
          <WhyBox detail={data} nowIso={state?.clock.sim_time ?? null} epoch={state?.clock.epoch} threshold={state?.carbon.debt_threshold ?? 350} />
          <Details className="mt-5">
          <Summary detail={data} nowIso={state?.clock.sim_time ?? null} threshold={state?.carbon.debt_threshold ?? 350} />
          <dl className="grid gap-x-8 sm:grid-cols-2">
            <div>
              <KV label="Application">{j.workload}</KV>
              <KV label="Priority">{j.priority} (1 = highest)</KV>
              <KV label="Estimated duration">{minutes(j.runtime_min)} at full speed</KV>
              <KV label="Actual elapsed">{elapsed(j.start_time, j.finish_time, state?.clock.sim_time ?? null)}</KV>
              <KV label="Progress">{Math.round(j.progress * 100)}% at {Math.round(j.capacity * 100)}% capacity</KV>
            </div>
            <div>
              <KV label="Arrived">{simClock(j.arrival_time, state?.clock.epoch)}</KV>
              <KV label="Deadline">{simClock(j.deadline_time, state?.clock.epoch)}{j.deadline_missed && <span className="ml-1 text-danger">missed</span>}</KV>
              <KV label="Time to deadline">{remaining(j.deadline_time, state?.clock.sim_time ?? null, j.finish_time)}</KV>
              <KV label="Started">{simClock(j.start_time, state?.clock.epoch)}</KV>
              <KV label={j.finish_time ? "Finished" : "Planned start"}>
                {simClock(j.finish_time ?? j.planned_start_time, state?.clock.epoch)}
              </KV>
            </div>
          </dl>
          <div>
            <Segmented<Tab>
              label="Job detail section"
              value={activeTab}
              onChange={setTab}
              options={[
                { value: "decisions", label: `All decisions (${data.decisions.length})` },
                { value: "history", label: "Status history" },
                { value: "executions", label: `Per step (${data.executions.length})` },
                { value: "ledger", label: `Debt records (${data.ledger.length})` },
                ...(data.receipt ? [{ value: "receipt" as Tab, label: "Carbon receipt" }] : []),
              ]}
            />
            {!data.receipt && <p className="mt-2 text-[13.5px] text-muted">The carbon receipt is issued once the job completes, fails or is cancelled.</p>}
          </div>
          {activeTab === "receipt" && data.receipt && <ReceiptView receipt={data.receipt} />}
          {activeTab === "history" && <History detail={data} />}
          {activeTab === "decisions" && (
            <ol className="space-y-3">
              {data.decisions.map((d) => (
                <li key={d.id} className="border-l-2 border-line-strong pl-3">
                  <div className="flex flex-wrap gap-x-2 text-[14px]">
                    <span className="tabular text-muted">{slotClock(d.slot)}</span>
                    <span className="font-medium">{ACTION_LABELS[d.action] ?? d.action}</span>
                    <span className="text-muted">{num(d.intensity)} gCO₂e/kWh</span>
                  </div>
                  <p className="mt-0.5 text-[14px] text-ink-2">{d.reason}</p>
                </li>
              ))}
            </ol>
          )}
          {activeTab === "executions" && (
            data.executions.length === 0 ? <p className="text-[14px] text-muted">The job has not executed yet.</p> : (
              <div className="overflow-x-auto">
                <table className="data-table w-full tabular">
                  <thead><tr><th>Slot</th><th>Capacity</th><th>Power</th><th>Energy</th><th>Intensity</th><th>Emissions</th><th>Debt</th><th>Kernel CPU</th></tr></thead>
                  <tbody>
                    {data.executions.map((e) => (
                      <tr key={e.slot}>
                        <td>{slotClock(e.slot)}</td><td>{Math.round(e.capacity * 100)}%</td><td>{num(e.power_w)} W</td>
                        <td>{num(e.energy_kwh, 3)} kWh</td><td>{num(e.intensity)}</td><td>{grams(e.emissions_g, 1)}</td>
                        <td>{grams(e.debt_g, 1)}</td><td>{e.kernel_cpu_ms === null ? "—" : `${num(e.kernel_cpu_ms, 1)} ms`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-[13.5px] text-muted">
                  {data.executions[0]?.energy_source === "MEASURED_RAPL_ATTRIBUTED"
                    ? "Energy is this process's estimated share of the measured CPU-package energy. Kernel CPU is its measured CPU time."
                    : "Energy is estimated from the declared power. Kernel CPU is real backend work measured per step."}
                </p>
              </div>
            )
          )}
          {activeTab === "ledger" && (
            data.ledger.length === 0 ? <p className="text-[14px] text-muted">No carbon-debt records for this process yet.</p> : (
              <ul className="space-y-3">
                {data.ledger.map((l) => (
                  <li key={l.seq} className="rounded-control border border-line px-3 py-2.5 text-[14px]">
                    <div className="flex flex-wrap gap-x-3">
                      <span className="font-mono text-ink-2">{l.event_id}</span>
                      <span className="font-medium">{l.event_type}</span>
                      <span className="tabular">{grams(l.amount_g, 3)}</span>
                      <span className="text-muted">balance {grams(l.balance_after_g, 3)}</span>
                    </div>
                    <div className="mt-1 break-all font-mono text-[13px] text-muted">{l.hash}</div>
                  </li>
                ))}
              </ul>
            )
          )}
          </Details>
        </>
      ) : null}
    </Drawer>
  );
}
