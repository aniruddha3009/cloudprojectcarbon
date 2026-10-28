import { Fragment, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Download, ShieldAlert, ShieldCheck } from "lucide-react";
import { api, downloadUrl } from "../lib/api";
import { useApp, usePollInterval } from "../lib/appState";
import { grams, gramsAuto, intensity, localTime, minutes, num, shortHash, simClock } from "../lib/format";
import { usePoll } from "../lib/hooks";
import type { LedgerEntry, VerifyResult } from "../lib/types";
import { Button, EmptyState, ErrorNote, Loading, PageHeader, Panel, Stat, TabPanel, Tabs, useToast } from "../components/ui";

const CHECKPOINT_KEY = "cdc.ledgerCheckpoint";
const TYPE_LABEL: Record<string, string> = {
  DEBT_INCURRED: "Debt added",
  DEFERRAL_RECORDED: "Process postponed (baseline saved)",
  CREDIT_VERIFIED: "Debt repaid",
  CREDIT_DENIED: "No repayment (not eligible)",
  DEBT_CLEARED: "Debt fully repaid",
};
const TYPE_TONE: Record<string, string> = {
  DEBT_INCURRED: "text-violet",
  CREDIT_VERIFIED: "text-clean",
  CREDIT_DENIED: "text-warn",
  DEBT_CLEARED: "text-clean",
  DEFERRAL_RECORDED: "text-ink-2",
};

function readCheckpoint(): { head: string; seq: number } | null {
  try {
    const raw = localStorage.getItem(CHECKPOINT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function VerifyPanel({ entries }: { entries: number }) {
  const { version } = useApp();
  const toast = useToast();
  const [checkpoint, setCheckpoint] = useState(readCheckpoint);
  const { data, error, refresh } = usePoll<VerifyResult>(() => api.verify(), 0, [version, entries]);
  const [againstCp, setAgainstCp] = useState<VerifyResult | null>(null);
  const [busy, setBusy] = useState(false);

  const save = () => {
    if (!data) return;
    const cp = { head: data.head_hash, seq: data.checked };
    try { localStorage.setItem(CHECKPOINT_KEY, JSON.stringify(cp)); } catch { /* per-viewer convenience only */ }
    setCheckpoint(cp);
    toast("success", `Checkpoint saved at entry ${cp.seq}. Copy the head hash somewhere outside this machine for real assurance.`);
  };
  const verifyCp = async () => {
    if (!checkpoint) return;
    setBusy(true);
    try {
      // The checkpoint must still be the head unless later entries were appended; check the stored prefix.
      const all = await api.ledger();
      const atSeq = all.find((e) => e.seq === checkpoint.seq);
      const result = await api.verify();
      const ok = result.ok && atSeq?.hash === checkpoint.head;
      setAgainstCp({ ...result, ok, status: ok ? "VERIFIED" : "TAMPERED",
        problems: ok ? [] : [...result.problems, `entry ${checkpoint.seq} no longer has the checkpointed hash`] });
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const ok = data?.ok;
  return (
    <Panel title="Hash-chain verification" sub="Every entry stores SHA-256 of its canonical fields plus the previous entry's hash."
      actions={<Button size="sm" onClick={refresh}>Verify now</Button>}>
      {error ? <ErrorNote message={error} /> : !data ? <Loading /> : (
        <>
          <div className="flex items-center gap-3">
            {ok ? <ShieldCheck className="h-8 w-8 text-clean" aria-hidden /> : <ShieldAlert className="h-8 w-8 text-danger" aria-hidden />}
            <div>
              <div className={`font-display text-[22px] font-semibold ${ok ? "text-clean" : "text-danger"}`}>{ok ? "Verified" : "Tampered"}</div>
              <div className="text-[14px] text-muted">{data.checked} entries checked{data.verified_at ? ` at ${localTime(data.verified_at)}` : ""}</div>
            </div>
          </div>
          {!ok && <ul className="mt-3 list-disc pl-5 text-[14px] text-danger">{data.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
          <div className="mt-4 text-[13.5px] text-muted">Chain head</div>
          <div className="break-all font-mono text-[13.5px] text-ink-2">{data.head_hash}</div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" onClick={save} disabled={!data.checked}>Save head as checkpoint</Button>
            <Button size="sm" variant="ghost" onClick={verifyCp} disabled={!checkpoint} busy={busy}>Verify against checkpoint</Button>
          </div>
          {checkpoint && <p className="mt-2 text-[13.5px] text-muted">Checkpoint: entry {checkpoint.seq}, {shortHash(checkpoint.head, 16)}</p>}
          {againstCp && (
            <p className={`mt-1 text-[14px] ${againstCp.ok ? "text-clean" : "text-danger"}`}>
              {againstCp.ok ? "The chain still contains the checkpointed entry unchanged." : againstCp.problems.join("; ")}
            </p>
          )}
          <p className="mt-3 text-[13.5px] leading-relaxed text-muted">
            A hash chain only proves integrity relative to a trusted head. Someone able to rewrite the whole database
            could recompute every hash, so the checkpoint must live somewhere they cannot reach.
          </p>
        </>
      )}
    </Panel>
  );
}

function TamperDemo() {
  const toast = useToast();
  const [field, setField] = useState("amount_g");
  const [seq, setSeq] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.tamper>> | null>(null);
  const run = async () => {
    setBusy(true);
    try {
      setResult(await api.tamper(field, seq ? Number(seq) : undefined));
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel title="Tamper-detection demonstration" sub="Alters an in-memory copy of the records. The stored records are never modified.">
      <div className="grid grid-cols-[1fr_110px] gap-3">
        <div>
          <label className="label" htmlFor="t-field">Change to make</label>
          <select id="t-field" className="input" value={field} onChange={(e) => setField(e.target.value)}>
            <option value="amount_g">Halve a debt amount</option>
            <option value="intensity_baseline">Inflate a baseline intensity</option>
            <option value="energy_kwh">Inflate recorded energy</option>
            <option value="job_id">Reassign the job</option>
            <option value="delete">Delete the entry</option>
            <option value="reorder">Swap with the next entry</option>
          </select>
        </div>
        <div>
          <label className="label" htmlFor="t-seq">Entry #</label>
          <input id="t-seq" className="input tabular" type="number" min={1} placeholder="auto" value={seq} onChange={(e) => setSeq(e.target.value)} />
        </div>
      </div>
      <Button className="mt-3" onClick={run} busy={busy}>Tamper with a copy and verify</Button>
      {result && (
        <div className="mt-4 space-y-2 text-[14px]">
          <p className="text-ink-2">Entry {result.target_seq}, {result.field}: <span className="font-mono">{result.before}</span> → <span className="font-mono">{result.after}</span></p>
          <p className="text-clean">Stored records: {result.original.status.toLowerCase()} ({result.original.checked} entries)</p>
          <p className="text-danger">Tampered copy: {result.tampered_copy.status.toLowerCase()}, first bad entry {result.tampered_copy.first_bad_seq}</p>
          <ul className="list-disc pl-5 text-muted">{result.tampered_copy.problems.slice(0, 4).map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      )}
    </Panel>
  );
}

function EntryDetail({ e }: { e: LedgerEntry }) {
  const d = e.details as Record<string, any>;
  const credit = e.event_type === "CREDIT_VERIFIED";
  return (
    <div className="grid gap-4 bg-bg px-4 py-4 text-[14px] md:grid-cols-2">
      <div className="space-y-1.5">
        {e.energy_kwh && <p><span className="text-muted">Energy: </span>{num(e.energy_kwh, 6)} kWh</p>}
        {e.intensity_actual && <p><span className="text-muted">Actual intensity: </span>{intensity(e.intensity_actual)}</p>}
        {e.intensity_baseline && <p><span className="text-muted">Baseline intensity: </span>{intensity(e.intensity_baseline)}</p>}
        {credit && (
          <p className="text-ink-2">
            Carbon avoided = {num(d.counterfactual_energy_kwh, 3)} kWh × {num(e.intensity_baseline, 2)} (baseline) − {num(d.actual_emissions_g, 3)} g (actual) = {num(d.credit_earned_g, 3)} g;
            {" "}{num(d.credit_applied_g, 3)} g used to repay debt, {num(d.surplus_not_banked_g, 3)} g extra not saved for later.
          </p>
        )}
        {e.event_type === "DEBT_INCURRED" && (
          <p className="text-ink-2">Debt = Σ per slot energy × (intensity − {d.debt_intensity_threshold}) = {num(e.amount_g, 3)} g; gross emissions {num(d.gross_emissions_g, 3)} g. Cause: {d.cause}.</p>
        )}
        {e.reference_event_id && <p><span className="text-muted">References: </span><span className="font-mono">{e.reference_event_id}</span></p>}
        {Array.isArray(d.reasons) && <p><span className="text-muted">Eligibility: </span>{d.reasons.join("; ")}</p>}
        {d.reason && <p><span className="text-muted">Reason: </span>{d.reason}</p>}
        <p><span className="text-muted">Recorded (wall clock): </span>{localTime(e.recorded_at)}</p>
      </div>
      <div className="space-y-1.5 font-mono text-[13px] break-all">
        <p><span className="font-sans text-muted">Idempotency key: </span>{e.idem_key}</p>
        <p><span className="font-sans text-muted">Previous hash: </span>{e.prev_hash}</p>
        <p><span className="font-sans text-muted">Hash: </span>{e.hash}</p>
      </div>
    </div>
  );
}

export default function Ledger({ onOpenJob }: { onOpenJob: (id: string) => void }) {
  const { version, state } = useApp();
  const interval = usePollInterval();
  const { data, error, loading, refresh } = usePoll(api.ledger, interval, [version]);
  const stats = usePoll(api.workloadStats, interval, [version]);
  const [type, setType] = useState("");
  const [jobQ, setJobQ] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const rows = useMemo(
    () => (data ?? []).filter((e) => (!type || e.event_type === type) && (!jobQ || (e.job_id ?? "").toLowerCase().includes(jobQ.toLowerCase()))),
    [data, type, jobQ],
  );
  const l = state?.ledger;
  const [tab, setTab] = useState<"entries" | "verify" | "workloads">("entries");
  return (
    <div>
      <PageHeader
        eyebrow="History" title="Carbon debt history"
        description="Every time carbon debt was added or repaid, in order. Records are only ever added, never changed, and the debt can never go below zero."
        actions={<a href={downloadUrl("/api/ledger/export.csv")} className="link-button"><Download className="h-4 w-4" aria-hidden /> Export CSV</a>}
      />
      {l && (
        <div className="mb-12 grid gap-5 sm:grid-cols-3">
          <Stat label="Carbon Debt Added" value={gramsAuto(l.total_debt_g)} tone="violet" hint="Recorded when each process finishes" />
          <Stat label="Carbon Debt Repaid" value={gramsAuto(l.credits_applied_g)} tone="clean" hint="Carbon avoided by postponed work that ran cleaner" />
          <Stat label="Carbon Debt Remaining" value={gramsAuto(l.balance_g)} hint={l.accrued_g > 0 ? `${gramsAuto(l.accrued_g)} more is being added by running processes` : undefined} />
        </div>
      )}
      <Tabs value={tab} onChange={setTab} tabs={[
        { value: "entries", label: "Records", count: data?.length ?? 0 },
        { value: "workloads", label: "By application" },
        { value: "verify", label: "Technical details" },
      ]} />
      <TabPanel id={tab}>
        {tab === "verify" && (
          <div className="grid gap-8 lg:grid-cols-2">
            <p className="text-[13.5px] text-muted lg:col-span-2">
              Each record stores a SHA-256 fingerprint of itself and of the record before it, so changing any old record is detected.
              This is not needed for the normal demo.
            </p>
            <VerifyPanel entries={data?.length ?? 0} />
            <TamperDemo />
          </div>
        )}
        {tab === "entries" && (      <Panel bodyClass="p-0" title="Records" sub="Click a record to see how the number was calculated."
        actions={<>
          <select className="input w-auto" value={type} onChange={(e) => setType(e.target.value)} aria-label="Filter by event type">
            <option value="">All record types</option>
            {Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <input className="input w-36" placeholder="Job ID" value={jobQ} onChange={(e) => setJobQ(e.target.value)} aria-label="Filter by job" />
        </>}>
        {error ? <div className="p-4"><ErrorNote message={error} onRetry={refresh} /></div> : loading && !data ? <div className="px-4"><Loading /></div> : rows.length === 0 ? (
          <div className="p-4"><EmptyState title={data?.length ? "No records match the filters" : "No carbon debt yet"} body={data?.length ? undefined : "Run the demo: urgent work on coal-heavy power adds debt; postponed work that runs on clean power repays it."} /></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full min-w-[900px] tabular">
              <thead><tr><th className="w-8"><span className="sr-only">Expand</span></th><th>#</th><th>Time</th><th>What happened</th><th>Process</th><th className="text-right">Change</th><th className="text-right">Debt before</th><th className="text-right">Debt after</th></tr></thead>
              <tbody>
                {rows.map((e) => (
                  <Fragment key={e.seq}>
                    <tr className="row-hover cursor-pointer" onClick={() => setOpen(open === e.seq ? null : e.seq)}>
                      <td>
                        <button aria-expanded={open === e.seq} aria-label={`Inspect entry ${e.seq}`} onClick={(ev) => { ev.stopPropagation(); setOpen(open === e.seq ? null : e.seq); }}>
                          {open === e.seq ? <ChevronDown className="h-4 w-4 text-muted" /> : <ChevronRight className="h-4 w-4 text-muted" />}
                        </button>
                      </td>
                      <td>{e.seq}</td>
                      <td>{simClock(e.sim_time, state?.clock.epoch)}</td>
                      <td className={TYPE_TONE[e.event_type]}>
                        {e.event_type === "CREDIT_VERIFIED" && Number(e.amount_g) === 0
                          ? "Ran cleaner, but no debt was left to repay"
                          : TYPE_LABEL[e.event_type] ?? e.event_type}
                      </td>
                      <td>{e.job_id ? <button className="font-mono text-[13.5px] hover:underline" onClick={(ev) => { ev.stopPropagation(); onOpenJob(e.job_id!); }}>{e.job_id}</button> : "—"}</td>
                      <td className="text-right">{Number(e.amount_g) === 0 ? "—" : grams(e.amount_g, 3)}</td>
                      <td className="text-right text-muted">{grams(e.balance_before_g, 3)}</td>
                      <td className="text-right">{grams(e.balance_after_g, 3)}</td>
                    </tr>
                    {open === e.seq && <tr><td colSpan={8} className="p-0"><EntryDetail e={e} /></td></tr>}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
        )}
        {tab === "workloads" && (
      <Panel title="By application" sub="How much carbon debt each application added and repaid.">
        {!stats.data?.length ? <p className="text-[14px] text-muted">No workloads yet.</p> : (
          <div className="overflow-x-auto">
            <table className="data-table w-full min-w-[760px] tabular">
              <thead><tr><th>Application</th><th>Finished</th><th className="text-right">Emissions</th><th className="text-right">Debt added</th><th className="text-right">Debt repaid</th><th className="text-right">Net</th><th>Postponements</th><th>Deadline misses</th><th>Avg delay</th></tr></thead>
              <tbody>
                {stats.data.map((s) => (
                  <tr key={s.workload}>
                    <td className="font-medium">{s.workload}</td>
                    <td>{s.completed}/{s.jobs}</td>
                    <td className="text-right">{grams(s.emissions_g)}</td>
                    <td className="text-right text-violet">{s.debt_g ? grams(s.debt_g) : "—"}</td>
                    <td className="text-right text-clean">{s.credit_g ? grams(s.credit_g) : "—"}</td>
                    <td className="text-right">{grams(s.net_g)}</td>
                    <td>{s.deferrals}</td>
                    <td className={s.deadline_misses ? "text-danger" : ""}>{s.deadline_misses}</td>
                    <td>{s.avg_delay_min === null ? "—" : minutes(s.avg_delay_min)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
        )}
      </TabPanel>
    </div>
  );
}
