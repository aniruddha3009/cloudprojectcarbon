import { useState } from "react";
import { Plus, Search } from "lucide-react";
import { api } from "../lib/api";
import { useApp, usePollInterval } from "../lib/appState";
import { usePoll } from "../lib/hooks";
import { AddProcess, QueueTable } from "../components/ProcessQueue";
import { LiveProcesses } from "../components/LiveProcesses";
import { Button, ConfirmDialog, EmptyState, ErrorNote, Loading, PageHeader, Panel, useToast } from "../components/ui";

const STATES: [string, string][] = [
  ["", "All statuses"], ["queued", "Waiting"], ["deferred", "Scheduled for later"], ["running", "Running"],
  ["paused", "Paused"], ["completed", "Completed"], ["failed", "Failed"], ["cancelled", "Cancelled"],
];

/** Process Queue page: the full queue with filters, adding processes and per-process actions. */
export default function Workloads({ onOpenJob }: { onOpenJob: (id: string) => void }) {
  const { version, bump, mode } = useApp();
  const toast = useToast();
  const interval = usePollInterval();
  const [q, setQ] = useState("");
  const [stateFilter, setStateFilter] = useState("");
  const [adding, setAdding] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const { data, error, loading, refresh } = usePoll(() => api.jobs({ q, state: stateFilter }), interval, [version, q, stateFilter]);

  const act = async (key: string, fn: () => Promise<unknown>, msg: string) => {
    setBusy(key);
    try {
      await fn();
      toast("success", msg);
      bump();
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
      setResetOpen(false);
    }
  };

  const live = mode === "live";
  const liveStatus = usePoll(() => (live ? api.liveStatus() : Promise.resolve(null)), live ? 2500 : 0, [live]);
  return (
    <div>
      <PageHeader
        eyebrow={live ? "Live processes" : "Simulated processes"}
        title="Process queue"
        description={live
          ? "Small test processes run by this app. Each row says what the scheduler decided and why."
          : "Each row says what the scheduler decided for the process and why. Click a row for the details."}
        actions={<>
          <Button variant="ghost" onClick={() => setResetOpen(true)}>{live ? "Clear live processes" : "Reset Demo"}</Button>
          <Button busy={busy === "demo"} onClick={() => act("demo", api.loadSamples, live ? "Four demo processes added; they run while monitoring is on." : "Four sample processes loaded at 06:00.")}>
            Load Sample Processes
          </Button>
          <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setAdding(true)}>Add Process</Button>
        </>}
      />

      <Panel bodyClass="p-0">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-6 py-5">
          <div className="relative min-w-[200px] flex-1">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
            <input className="input pl-11" placeholder="Search by name" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search processes" />
          </div>
          <select className="input w-auto" value={stateFilter} onChange={(e) => setStateFilter(e.target.value)} aria-label="Filter by status">
            {STATES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        {error ? <div className="p-6"><ErrorNote message={error} onRetry={refresh} /></div> : loading && !data ? <div className="px-6"><Loading /></div> : !data?.length ? (
          <div className="p-6">
            <EmptyState
              title={q || stateFilter ? "No processes match" : "No processes yet"}
              body={q || stateFilter ? "Clear the search or filter." : "Load the sample processes or add your own."}
            />
          </div>
        ) : <QueueTable jobs={data} onOpenJob={onOpenJob} actions />}
      </Panel>
      <p className="mt-3 text-[12.5px] text-faint">
        {live ? "Only these test processes are controlled by the scheduler. The real CPU processes below are watched, never controlled."
          : "Run now starts a process at the next step regardless of carbon; it then cannot earn a repayment."}
      </p>
      {live && liveStatus.data && (
        <div className="mt-6">
          <LiveProcesses processes={liveStatus.data.telemetry.processes} refreshedAt={liveStatus.data.telemetry.refreshed_at} />
        </div>
      )}
      <AddProcess open={adding} onClose={() => setAdding(false)} />
      <ConfirmDialog
        open={resetOpen}
        title={live ? "Clear live processes?" : "Reset the demo?"}
        body={live
          ? "Live processes and their carbon-debt history are deleted. Real grid readings are kept. Simulation data is not touched."
          : "All simulated processes and carbon-debt history are deleted, the clock returns to 06:00 and the grid returns to its normal daily pattern. Experiments are kept."}
        confirmLabel={live ? "Clear" : "Reset"}
        danger
        busy={busy === "reset"}
        onCancel={() => setResetOpen(false)}
        onConfirm={() => act("reset", api.reset, live ? "Live processes cleared." : "Demo reset to 06:00.")}
      />
    </div>
  );
}
