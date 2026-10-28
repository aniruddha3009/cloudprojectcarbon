import { useMemo, useState } from "react";
import { api } from "../lib/api";
import { localTime, num } from "../lib/format";
import { usePoll } from "../lib/hooks";
import type { ProcessRow } from "../lib/types";
import { Badge, Panel } from "./ui";

/** The real processes running on this laptop right now, busiest CPU first. Watched only, never controlled. */
export function LiveProcesses({ processes, refreshedAt, limit = 25 }: { processes: ProcessRow[]; refreshedAt: string | null; limit?: number }) {
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return processes
      .filter((r) => !needle || r.name.toLowerCase().includes(needle) || String(r.pid) === needle)
      .sort((a, b) => (b.cpu_percent ?? -1) - (a.cpu_percent ?? -1) || (b.memory_mb ?? 0) - (a.memory_mb ?? 0))
      .slice(0, needle ? 200 : limit);
  }, [processes, q, limit]);
  const busy = processes.filter((p) => (p.cpu_percent ?? 0) > 0).length;
  // A deployed backend watches its own server, not the viewer's laptop: say so.
  const health = usePoll(api.health, 0, []);
  const cloud = health.data?.environment === "production";
  const where = cloud ? "the cloud server running this app (not your laptop)" : "this laptop";
  return (
    <Panel title={cloud ? "CPU processes on the server" : "CPU processes on this laptop"}
      sub={processes.length
        ? `${processes.length} processes on ${where}, ${busy} using CPU now · refreshed ${refreshedAt ? localTime(refreshedAt) : "—"}. Watched only — the scheduler does not control them.`
        : "Watched only — the scheduler does not control them."}
      actions={<input className="input w-56" placeholder="Search name or PID" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search processes" />}
      bodyClass="px-0 pb-2">
      {processes.length === 0 ? <p className="px-6 pb-4 text-[13.5px] text-muted">Reading processes… the first CPU figures appear after a few seconds.</p> : (
        <div data-lenis-prevent className="max-h-[440px] overflow-auto">
          <table className="data-table w-full tabular-nums">
            <thead><tr><th>Process</th><th className="!text-right">PID</th><th>Status</th><th className="!text-right">CPU</th><th className="!text-right">Memory</th><th>Started</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.pid}>
                  <td className="font-medium">{r.name}{r.is_app_backend && <Badge tone="accent" className="ml-2">this app</Badge>}</td>
                  <td className="text-right text-ink-2">{r.pid}</td>
                  <td className="text-ink-2">{r.status ?? <span className="text-faint">—</span>}</td>
                  <td className="text-right">{r.cpu_percent === null ? <span className="text-faint">—</span> : `${num(r.cpu_percent, 1)}%`}</td>
                  <td className="text-right">{r.memory_mb === null ? <span className="text-faint">—</span> : `${num(r.memory_mb, 0)} MB`}</td>
                  <td className="whitespace-nowrap text-ink-2">{r.started_at ? localTime(r.started_at) : <span className="text-faint">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
