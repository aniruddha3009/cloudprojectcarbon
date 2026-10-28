import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useApp } from "../lib/appState";
import { CLASS_LABELS, gramsAuto, num, simClock } from "../lib/format";
import type { Job, JobClass } from "../lib/types";
import { Button, ClassBadge, ConfirmDialog, Drawer, ErrorNote, StatusBadge, useToast } from "./ui";

/** The time shown in the "Scheduled time" column, taken from the job's real state. */
function scheduledTime(j: Job, epoch?: string): string {
  if (j.state === "deferred" && j.planned_start_time && j.status_label === "Scheduled for later") return simClock(j.planned_start_time, epoch);
  if (j.state === "running" || j.state === "paused") return `Started ${simClock(j.start_time, epoch)}`;
  if (j.finish_time) return `Done ${simClock(j.finish_time, epoch)}`;
  if (j.state === "pending" && j.status_label === "Not arrived yet") return `Arrives ${simClock(j.arrival_time, epoch)}`;
  return "Next step";
}

function Actions({ job }: { job: Job }) {
  const { bump } = useApp();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const run = async (action: string) => {
    setBusy(action);
    try {
      await api.jobAction(job.id, action, action === "defer" ? 60 : undefined);
      toast("success", action === "run" ? `${job.name} will start at the next step.` : action === "defer" ? `${job.name} held for 60 minutes.` : `${job.name} cancelled.`);
      bump();
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
      setConfirmCancel(false);
    }
  };
  if (!job.available_actions.length) return null;
  return (
    <div className="flex justify-end gap-1">
      {job.available_actions.includes("run") && (
        <Button size="sm" variant="ghost" busy={busy === "run"} onClick={() => run("run")} disabled={job.manual_run_pending}
          title="Start it at the next step regardless of carbon (it then cannot earn a repayment)">
          {job.manual_run_pending ? "Starting next step" : "Run now"}
        </Button>
      )}
      <Button size="sm" variant="ghost" busy={busy === "cancel"} onClick={() => setConfirmCancel(true)}>Cancel</Button>
      <ConfirmDialog
        open={confirmCancel}
        title={`Cancel ${job.name}?`}
        body={job.state === "running" || job.state === "paused"
          ? "The process stops now. The energy it already used, and any carbon debt it caused, stay counted."
          : "The process will never run."}
        confirmLabel="Cancel process"
        danger
        busy={busy === "cancel"}
        onCancel={() => setConfirmCancel(false)}
        onConfirm={() => run("cancel")}
      />
    </div>
  );
}

/** Process | Priority | Status | Scheduled time | Reason. Every value comes from the backend job record. */
export function QueueTable({ jobs, onOpenJob, actions = false }: { jobs: Job[]; onOpenJob: (id: string) => void; actions?: boolean }) {
  const { state } = useApp();
  const epoch = state?.clock.epoch;
  return (
    <div data-lenis-prevent className="scroll-area overflow-x-auto">
      <table className="data-table w-full min-w-[860px]">
        <thead>
          <tr>
            <th>Process</th><th>Priority</th><th>Status</th><th>Scheduled time</th><th>Reason</th>
            {actions && <th><span className="sr-only">Actions</span></th>}
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id} className="row-hover cursor-pointer" onClick={() => onOpenJob(j.id)}>
              <td>
                <div className="text-[15px] font-medium text-ink">{j.name}</div>
                <div className="mt-1 flex items-center gap-2"><ClassBadge jobClass={j.job_class} />
                  {(j.debt_g > 0 || j.credit_g > 0) && (
                    <span className="text-[12.5px] tabular-nums">
                      {j.debt_g > 0 && <span className="text-lav-ink">+{gramsAuto(j.debt_g)} debt</span>}
                      {j.debt_g > 0 && j.credit_g > 0 && " · "}
                      {j.credit_g > 0 && <span className="text-ok">repaid {gramsAuto(j.credit_g)}</span>}
                    </span>
                  )}
                </div>
              </td>
              <td className="tabular-nums text-ink-2">{j.priority}{j.priority === 1 ? " (highest)" : ""}</td>
              <td>
                <StatusBadge label={j.status_label} />
                {j.state === "running" && j.capacity < 1 && <div className="mt-1 text-[12.5px] text-warn">{Math.round(j.capacity * 100)}% speed</div>}
                {j.deadline_missed && <div className="mt-1 text-[12.5px] text-bad">Deadline missed</div>}
              </td>
              <td className="whitespace-nowrap tabular-nums text-ink-2">{scheduledTime(j, epoch)}</td>
              <td className="max-w-[440px] text-[13.5px] leading-snug text-ink-2">
                {j.plain_reason}
                <button className="ml-2 text-[12.5px] font-semibold text-lav-ink hover:underline" onClick={(e) => { e.stopPropagation(); onOpenJob(j.id); }}>
                  Why this decision?
                </button>
              </td>
              {actions && <td onClick={(e) => e.stopPropagation()}><Actions job={j} /></td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface FormState {
  name: string; job_class: JobClass; priority: number; power_w: number; runtime_min: number; deadline_offset_min: number;
  workload: string; arrival_offset_min: number; max_wait_min: string; simulate_failure: boolean;
}
const SIM_DEFAULT: FormState = {
  name: "", job_class: "normal", priority: 3, power_w: 800, runtime_min: 60, deadline_offset_min: 480,
  workload: "demo", arrival_offset_min: 0, max_wait_min: "", simulate_failure: false,
};
const LIVE_DEFAULT: FormState = { ...SIM_DEFAULT, runtime_min: 2, deadline_offset_min: 15 };

export function AddProcess({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { bump, mode } = useApp();
  const live = mode === "live";
  const toast = useToast();
  const [form, setForm] = useState<FormState>(live ? LIVE_DEFAULT : SIM_DEFAULT);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setForm(live ? LIVE_DEFAULT : SIM_DEFAULT); setErr(null); }, [live, open]);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm((f) => ({ ...f, [k]: v }));
  const problems: string[] = [];
  if (!form.name.trim()) problems.push("Give the process a name.");
  if (!/^[A-Za-z0-9][A-Za-z0-9 _.-]*$/.test(form.workload.trim())) problems.push("Application name must start with a letter or digit.");
  if (live) {
    if (form.runtime_min < 1 || form.runtime_min > 10) problems.push("Live processes run 1–10 minutes so they stay small.");
    if (form.deadline_offset_min > 240) problems.push("Live deadlines must be within 4 hours.");
  } else {
    if (form.runtime_min % 15 || form.runtime_min < 15) problems.push("Run time must be a multiple of 15 minutes.");
    if (form.deadline_offset_min % 15) problems.push("Deadline must be a multiple of 15 minutes.");
    if (form.power_w < 10 || form.power_w > 10000) problems.push("Power must be between 10 and 10 000 W.");
  }
  if (form.deadline_offset_min < form.runtime_min) problems.push("The deadline is shorter than the run time, so it could never be met.");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (problems.length) return;
    setBusy(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = {
        ...form, name: form.name.trim(), workload: form.workload.trim(),
        max_wait_min: form.max_wait_min ? Number(form.max_wait_min) : null,
        idempotency_key: `ui-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      };
      if (live) { delete body.power_w; body.arrival_offset_min = 0; body.simulate_failure = false; }
      await api.createJob(body);
      toast("success", `${form.name.trim()} added. It is considered at the next step.`);
      bump();
      onClose();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
    } finally {
      setBusy(false);
    }
  };

  const step = live ? 1 : 15;
  const energy = (form.power_w * form.runtime_min) / 60 / 1000;
  return (
    <Drawer open={open} onClose={onClose} width="max-w-lg" title={<h2 className="font-display text-[22px] font-light">Add a process</h2>}>
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <p className="text-[13.5px] text-muted">
          {live ? "A small CPU task run by this app (never an existing Windows program). Its energy is measured while it runs."
            : "A simulated process. Its energy is estimated from the power you enter."}
        </p>
        <div>
          <label className="label" htmlFor="f-name">Name</label>
          <input id="f-name" className="input" value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Monthly sales report" maxLength={120} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="f-class">How flexible is it?</label>
            <select id="f-class" className="input" value={form.job_class} onChange={(e) => set("job_class", e.target.value as JobClass)}>
              {(["emergency", "normal", "background"] as JobClass[]).map((c) => <option key={c} value={c}>{CLASS_LABELS[c]}</option>)}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="f-prio">Priority</label>
            <select id="f-prio" className="input" value={form.priority} onChange={(e) => set("priority", Number(e.target.value))}>
              {[1, 2, 3, 4, 5].map((p) => <option key={p} value={p}>{p}{p === 1 ? " (highest)" : p === 5 ? " (lowest)" : ""}</option>)}
            </select>
          </div>
        </div>
        <div className={`grid gap-3 ${live ? "grid-cols-2" : "grid-cols-3"}`}>
          {!live && (
            <div>
              <label className="label" htmlFor="f-power">Power (W)</label>
              <input id="f-power" type="number" className="input" min={10} max={10000} value={form.power_w} onChange={(e) => set("power_w", Number(e.target.value))} />
            </div>
          )}
          <div>
            <label className="label" htmlFor="f-runtime">Run time (min)</label>
            <input id="f-runtime" type="number" className="input" min={step} step={step} value={form.runtime_min} onChange={(e) => set("runtime_min", Number(e.target.value))} />
          </div>
          <div>
            <label className="label" htmlFor="f-dl">Deadline (min from now)</label>
            <input id="f-dl" type="number" className="input" min={step} step={step} value={form.deadline_offset_min} onChange={(e) => set("deadline_offset_min", Number(e.target.value))} />
          </div>
        </div>
        <p className="text-[13px] text-faint">
          {live ? "Energy is measured while it runs." : `Estimated energy: ${num(energy, 2)} kWh (power × run time).`}
          {" "}A long deadline makes the process flexible: the scheduler may move it to a cleaner time.
        </p>
        {!live && (
          <details className="rounded-2xl border border-line px-4 py-3 text-[13.5px]">
            <summary className="cursor-pointer font-semibold text-ink-2">More options</summary>
            <div className="mt-3 grid grid-cols-3 gap-3">
              <div>
                <label className="label" htmlFor="f-workload">Application</label>
                <input id="f-workload" className="input" value={form.workload} onChange={(e) => set("workload", e.target.value)} maxLength={60} />
              </div>
              <div>
                <label className="label" htmlFor="f-arr">Arrives in (min)</label>
                <input id="f-arr" type="number" className="input" min={0} step={15} value={form.arrival_offset_min} onChange={(e) => set("arrival_offset_min", Number(e.target.value))} />
              </div>
              <div>
                <label className="label" htmlFor="f-wait">Max wait (min)</label>
                <input id="f-wait" type="number" className="input" min={15} step={15} placeholder="none" value={form.max_wait_min} onChange={(e) => set("max_wait_min", e.target.value)} />
              </div>
            </div>
            <label className="mt-3 flex items-center gap-2 text-ink-2">
              <input type="checkbox" checked={form.simulate_failure} onChange={(e) => set("simulate_failure", e.target.checked)} />
              Make it fail halfway (to show how failed work is counted)
            </label>
          </details>
        )}
        {problems.length > 0 && form.name && (
          <ul className="list-disc pl-5 text-[13.5px] text-warn">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
        )}
        {err && <ErrorNote message={err} />}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={problems.length > 0}>Add process</Button>
        </div>
      </form>
    </Drawer>
  );
}
