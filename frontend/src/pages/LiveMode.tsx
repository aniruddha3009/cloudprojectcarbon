import { useState } from "react";
import { LiveProcesses } from "../components/LiveProcesses";
import { api, getAdminToken, setAdminToken } from "../lib/api";
import { useApp } from "../lib/appState";
import { gridLevel, localTime, num } from "../lib/format";
import { usePoll } from "../lib/hooks";
import type { GridStatus, LiveStatus } from "../lib/types";
import { Button, Details, ErrorNote, KV, Loading, PageHeader, Panel, Stat, StateBadge, useToast } from "../components/ui";

function age(seconds: number | null): string {
  if (seconds === null) return "";
  if (seconds < 90) return `${seconds} s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  return `${(seconds / 3600).toFixed(1)} h ago`;
}

/** Live Grid Data: the real India Energy Atlas reading, or a clear Unavailable state. */
export function LiveGridCard({ grid, green, debt }: { grid: GridStatus; green: number; debt: number }) {
  // A failed fetch does not erase the last real reading: show it with its time and the failure reason.
  const ok = grid.intensity !== null && grid.state !== "not_configured";
  const level = gridLevel(ok ? grid.intensity : null, green, debt);
  const failed = grid.state === "error";
  return (
    <Stat
      label="Live Grid Data"
      tone={level.tone}
      value={ok ? <>{num(grid.intensity)}<span className="ml-1.5 font-sans text-[13px] font-medium tracking-normal text-muted">gCO₂e/kWh</span></> : "Unavailable"}
      hint={ok ? (
        <>
          <span className="font-semibold">{level.label}</span>
          {grid.state === "stale" && <span className="text-warn"> · reading is old</span>}
          <br />Updated {grid.reading_time ? localTime(grid.reading_time) : "—"} ({age(grid.age_seconds)}) · {grid.provider}, {grid.region}
          {failed && (
            <span className="mt-1 block text-warn">
              Latest fetch failed ({grid.error?.message}). Showing the last real reading; retrying {grid.next_poll ? `at ${localTime(grid.next_poll)}` : "soon"}.
            </span>
          )}
        </>
      ) : (grid.error?.message ?? (grid.state === "waiting" ? "Waiting for the first reading." : "No reading yet. Start monitoring."))}
    />
  );
}

export function ControlNote() {
  return (
    <Panel title="What the scheduler can and cannot control">
      <ul className="list-disc space-y-1.5 pl-5 text-[13.5px] leading-relaxed text-ink-2">
        <li><span className="font-medium">Can:</span> start, delay, slow down or pause the small test processes that <em>this app</em> creates (listed in the Process Queue).</li>
        <li><span className="font-medium">Cannot:</span> pause, slow down or close any other Windows program. Those are only watched: their name, CPU and memory.</li>
        <li>The grid reading comes from India Energy Atlas (hourly, all-India). If it is unavailable, the app shows “Unavailable” and live processes wait — it never invents a value.</li>
      </ul>
    </Panel>
  );
}

function Laptop({ live }: { live: LiveStatus }) {
  const sys = live.telemetry.system;
  const meter = live.telemetry.energy_meter;
  return (
    <Stat
      label="Live Process Monitoring"
      value={sys ? <>{num(sys.cpu_percent)}%<span className="mx-1.5 text-faint">CPU</span>{num(sys.memory_percent)}%<span className="ml-1.5 text-faint">memory</span></> : "Unavailable"}
      hint={sys ? (
        <>
          {live.telemetry.processes.length} processes detected · refreshed {localTime(live.telemetry.refreshed_at)}
          <br />CPU power: {sys.package_power_w === null ? "unavailable" : `${num(sys.package_power_w, 1)} W (measured)`}
          {!meter.available && " · energy is estimated from CPU time"}
        </>
      ) : "Reading this laptop's processes…"}
    />
  );
}

function GridTechnical({ grid }: { grid: GridStatus }) {
  const { bump } = useApp();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const refresh = async () => {
    setBusy(true);
    try {
      const s = await api.refreshGrid();
      toast(s.state === "ok" ? "success" : "warning", s.state === "ok" ? "Grid reading updated." : s.error?.message ?? "No reading.");
      bump();
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <div className="mb-2 flex items-center gap-3">
        <h3 className="text-[14px] font-semibold text-ink-2">Grid feed</h3>
        <Button size="sm" busy={busy} onClick={refresh} disabled={!grid.configured}>Fetch now</Button>
      </div>
      <dl>
        <KV label="Status">{grid.state.replace("_", " ")}</KV>
        <KV label="Last successful update">{grid.last_success ? localTime(grid.last_success) : "—"}</KV>
        <KV label="Next scheduled fetch">{grid.next_poll ? localTime(grid.next_poll) : "when monitoring starts"}</KV>
        <KV label="Largest fuel source">{grid.dominant_fuel ?? "—"}</KV>
        <KV label="API calls today" hint="Free keys allow 100 calls per day">{grid.calls_today} (every {num(grid.poll_minutes)} min)</KV>
        <KV label="Forecast hours stored">{grid.forecast_points}</KV>
      </dl>
      <p className="mt-2 text-[12px] text-faint">{grid.notes}</p>
    </div>
  );
}

function AdminToken() {
  const toast = useToast();
  const [value, setValue] = useState(getAdminToken());
  return (
    <div>
      <h3 className="mb-1 text-[14px] font-semibold text-ink-2">Admin token</h3>
      <p className="mb-2 text-[12.5px] text-muted">Only needed when the backend sets ADMIN_TOKEN (public deployments).</p>
      <div className="flex gap-2">
        <input type="password" className="input" value={value} onChange={(e) => setValue(e.target.value)} placeholder="Paste the ADMIN_TOKEN value" aria-label="Admin token" autoComplete="off" />
        <Button onClick={() => { setAdminToken(value.trim()); toast("success", value.trim() ? "Token saved in this browser." : "Token cleared."); }}>Save</Button>
      </div>
    </div>
  );
}

export default function LiveMode() {
  const { state, version, bump } = useApp();
  const toast = useToast();
  const live = state?.mode === "live";
  const [busy, setBusy] = useState(false);
  const liveStatus = usePoll(() => (live ? api.liveStatus() : Promise.resolve(null)), live ? 2500 : 0, [version, live]);
  const notes = usePoll(api.telemetry, 0, [version]);

  const act = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    try {
      await fn();
      toast("info", msg);
      bump();
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!state) return <Loading />;
  if (!live) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader eyebrow="Live Mode" title="Real grid data and this laptop's processes."
          description="Live Mode reads the real all-India carbon intensity from India Energy Atlas and watches the programs running on this laptop. It uses its own database, so simulated and real records never mix." />
        <Panel title="You are in Simulation mode">
          <p className="text-[14px] text-ink-2">Switch to Live mode to see real data. You can switch back at any time; the simulation is kept.</p>
          <Button className="mt-4" variant="primary" busy={busy} onClick={() => act(() => api.setMode("live"), "Live mode: press Start monitoring to collect real data.")}>Switch to Live mode</Button>
        </Panel>
        <Panel><AdminToken /></Panel>
        <ControlNote />
      </div>
    );
  }
  const monitoring = state.clock.autoplay;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader eyebrow="Live Mode" title="Real grid data and this laptop's processes."
        description="Nothing on this page is simulated. If a reading is missing, it says Unavailable."
        actions={<Button variant={monitoring ? "secondary" : "primary"} busy={busy}
          onClick={() => act(() => api.monitoring(!monitoring), monitoring ? "Monitoring stopped." : "Monitoring started.")}>
          {monitoring ? "Stop monitoring" : "Start monitoring"}
        </Button>} />
      {liveStatus.error ? <ErrorNote message={liveStatus.error} /> : !liveStatus.data ? <Loading /> : (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <LiveGridCard grid={liveStatus.data.grid} green={state.carbon.green_threshold} debt={state.carbon.debt_threshold} />
            <Laptop live={liveStatus.data} />
          </div>
          <ControlNote />
          <LiveProcesses processes={liveStatus.data.telemetry.processes} refreshedAt={liveStatus.data.telemetry.refreshed_at} />
          <Details>
            <GridTechnical grid={liveStatus.data.grid} />
            <div>
              <h3 className="mb-1 text-[14px] font-semibold text-ink-2">Energy measurement</h3>
              <p className="text-[13px] text-muted">{liveStatus.data.telemetry.energy_meter.available ? `${liveStatus.data.telemetry.energy_meter.source}. ` : ""}{liveStatus.data.telemetry.energy_meter.message}</p>
              <p className="mt-1 text-[13px] text-muted">Each managed process gets an <span className="font-medium">estimated</span> share of the measured CPU energy, in proportion to its CPU time.</p>
            </div>
            {liveStatus.data.managed_workloads.length > 0 && (
              <div>
                <h3 className="mb-1 text-[14px] font-semibold text-ink-2">Processes managed by this app</h3>
                <table className="data-table w-full tabular-nums">
                  <thead><tr><th>Process</th><th>State</th><th className="!text-right">Speed</th><th className="!text-right">CPU time</th></tr></thead>
                  <tbody>
                    {liveStatus.data.managed_workloads.map((j) => (
                      <tr key={j.id}><td>{j.name}</td><td><StateBadge state={j.state} /></td>
                        <td className="text-right">{Math.round(j.capacity * 100)}%</td><td className="text-right">{num(j.cpu_ms_total / 1000, 2)} s</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {notes.data && (
              <ul className="list-disc space-y-1 pl-5 text-[13px] text-muted">{notes.data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
            )}
            <AdminToken />
          </Details>
        </>
      )}
    </div>
  );
}
