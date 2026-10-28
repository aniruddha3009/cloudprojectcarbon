import { useMemo } from "react";
import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { CurvePoint, GanttJob, TimelinePoint } from "../lib/types";
import { grams, num, slotClock } from "../lib/format";

export const SLOTS_PER_DAY = 96;

export function dayWindow(slot: number): [number, number] {
  const day = Math.floor(Math.max(slot - 1, 0) / SLOTS_PER_DAY);
  return [day * SLOTS_PER_DAY, (day + 1) * SLOTS_PER_DAY];
}

function ticks([a, b]: [number, number]): number[] {
  const out: number[] = [];
  for (let s = a; s <= b; s += 12) out.push(s); // every 3 h
  return out;
}

function TooltipBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-3 py-2 text-[14px] shadow-lg">{children}</div>
  );
}

/** Contiguous runs of slots at/below the green threshold → shaded bands. */
function greenRuns(points: CurvePoint[], threshold: number, [a, b]: [number, number]) {
  const runs: [number, number][] = [];
  let start: number | null = null;
  for (const p of points) {
    if (p.slot < a || p.slot > b) continue;
    if (p.intensity <= threshold) {
      if (start === null) start = p.slot;
    } else if (start !== null) {
      runs.push([start, p.slot]);
      start = null;
    }
  }
  if (start !== null) runs.push([start, b]);
  return runs;
}

export function IntensityChart({ points, current, greenThreshold, debtThreshold, window, height = 260, projection }: {
  points: CurvePoint[]; current: number; greenThreshold: number; debtThreshold: number; window: [number, number];
  height?: number; projection?: boolean;
}) {
  const data = useMemo(
    () =>
      points
        .filter((p) => p.slot >= window[0] && p.slot <= window[1])
        .map((p) => ({
          slot: p.slot,
          source: p.source,
          observed: p.slot <= current ? p.intensity : null,
          forecast: p.slot >= current ? p.intensity : null,
          value: p.intensity,
        })),
    [points, current, window],
  );
  const runs = useMemo(() => greenRuns(points, greenThreshold, window), [points, greenThreshold, window]);
  const max = Math.max(700, ...data.map((d) => d.value));
  return (
    <div style={{ height }} role="img" aria-label={`Grid carbon intensity from ${slotClock(window[0])} to ${slotClock(window[1])}; green windows shaded`}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid vertical={false} />
          {runs.map(([s, e]) => (
            <ReferenceArea key={s} x1={s} x2={e} y1={0} y2={max} fill="var(--clean)" fillOpacity={0.09} stroke="none" ifOverflow="hidden" />
          ))}
          <XAxis dataKey="slot" type="number" domain={window} ticks={ticks(window)} tickFormatter={slotClock}
            tickLine={false} axisLine={{ stroke: "var(--line-strong)" }} />
          <YAxis domain={[0, Math.ceil(max / 100) * 100]} tickLine={false} axisLine={false} width={48} />
          <ReferenceLine y={debtThreshold} stroke="var(--danger)" strokeDasharray="4 4" strokeOpacity={0.7}
            label={{ value: `Debt threshold ${debtThreshold}`, position: "insideTopRight", fill: "var(--muted)", fontSize: 13 }} />
          <ReferenceLine y={greenThreshold} stroke="var(--clean)" strokeDasharray="4 4" strokeOpacity={0.7}
            label={{ value: `Green ≤ ${greenThreshold}`, position: "insideBottomRight", fill: "var(--muted)", fontSize: 13 }} />
          {current >= window[0] && current <= window[1] && (
            <ReferenceLine x={current} stroke="var(--violet)" strokeWidth={1.5}
              label={{ value: "Now", position: "insideTopLeft", fill: "var(--violet)", fontSize: 13 }} />
          )}
          <Tooltip
            cursor={{ stroke: "var(--line-strong)" }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0].payload as (typeof data)[number];
              const status = d.value <= greenThreshold ? "Green window" : d.value > debtThreshold ? "Above debt threshold" : "Moderate";
              return (
                <TooltipBox>
                  <div className="font-medium text-ink">{slotClock(d.slot)} UTC</div>
                  <div className="tabular text-ink-2">{num(d.value)} gCO₂e/kWh</div>
                  <div className="text-muted">{status} · {d.slot > current ? "forecast" : "observed"} · {d.source.toLowerCase()}</div>
                </TooltipBox>
              );
            }}
          />
          <Area dataKey="observed" type="monotone" stroke="var(--ink)" strokeWidth={2} fill="var(--ink)" fillOpacity={0.05}
            isAnimationActive={false} connectNulls={false} dot={false} activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }} />
          <Line dataKey="forecast" type="monotone" stroke="var(--muted)" strokeWidth={2}
            strokeDasharray={projection === false ? undefined : "5 4"} dot={false} isAnimationActive={false}
            activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DebtChart({ points, window, height = 170, projection }: {
  points: TimelinePoint[]; window: [number, number]; height?: number;
  projection?: { slot: number; balance_g: number }[];
}) {
  const data = useMemo(() => {
    const rows: Record<number, { slot: number; effective?: number; balance?: number; projected?: number }> = {};
    for (const p of points) {
      if (p.slot < window[0] || p.slot > window[1]) continue;
      rows[p.slot] = { slot: p.slot + 1, effective: p.effective_debt_g, balance: p.balance_g };
    }
    for (const p of projection ?? []) {
      if (p.slot < window[0] || p.slot > window[1]) continue;
      rows[p.slot] = { ...(rows[p.slot] ?? { slot: p.slot }), slot: p.slot, projected: p.balance_g };
    }
    return Object.values(rows).sort((a, b) => a.slot - b.slot);
  }, [points, window, projection]);
  const max = Math.max(100, ...data.map((d) => Math.max(d.effective ?? 0, d.projected ?? 0)));
  return (
    <div style={{ height }} role="img" aria-label="Carbon debt balance over time">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="slot" type="number" domain={window} ticks={ticks(window)} tickFormatter={slotClock}
            tickLine={false} axisLine={{ stroke: "var(--line-strong)" }} />
          <YAxis domain={[0, Math.ceil(max / 200) * 200]} tickLine={false} axisLine={false} width={48} />
          <Tooltip
            cursor={{ stroke: "var(--line-strong)" }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0].payload as (typeof data)[number];
              return (
                <TooltipBox>
                  <div className="font-medium text-ink">{slotClock(d.slot)} UTC</div>
                  {d.effective !== undefined && <div className="tabular text-ink-2">Effective debt {grams(d.effective, 1)}</div>}
                  {d.balance !== undefined && <div className="tabular text-muted">Recorded {grams(d.balance, 1)}</div>}
                  {d.projected !== undefined && <div className="tabular text-violet">Projected {grams(d.projected, 1)}</div>}
                </TooltipBox>
              );
            }}
          />
          <Area dataKey="effective" type="stepAfter" stroke="var(--violet)" strokeWidth={2} fill="var(--violet)"
            fillOpacity={0.16} isAnimationActive={false} dot={false} connectNulls />
          <Line dataKey="balance" type="stepAfter" stroke="var(--ink-2)" strokeWidth={1.5} strokeDasharray="2 3"
            dot={false} isAnimationActive={false} connectNulls />
          {projection && (
            <Line dataKey="projected" type="stepAfter" stroke="var(--violet)" strokeWidth={2} strokeDasharray="6 4"
              dot={false} isAnimationActive={false} connectNulls />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ChartLegend({ items }: { items: { label: string; color: string; dashed?: boolean; band?: boolean }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[13.5px] text-ink-2">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5">
          {i.band ? (
            <span className="h-3 w-4 rounded-sm" style={{ background: i.color, opacity: 0.35 }} aria-hidden />
          ) : (
            <svg width="18" height="6" aria-hidden>
              <line x1="0" y1="3" x2="18" y2="3" stroke={i.color} strokeWidth="2" strokeDasharray={i.dashed ? "4 3" : undefined} />
            </svg>
          )}
          {i.label}
        </li>
      ))}
    </ul>
  );
}

/** Workload execution timeline. Segment height = capacity share; colour = grid intensity it ran at. */
export function Gantt({ jobs, current, window, greenThreshold, debtThreshold, onSelect }: {
  jobs: GanttJob[]; current: number; window: [number, number]; greenThreshold: number; debtThreshold: number;
  onSelect?: (id: string) => void;
}) {
  const span = window[1] - window[0];
  const x = (slot: number) => `${((slot - window[0]) / span) * 100}%`;
  const w = (n: number) => `${(n / span) * 100}%`;
  const color = (i: number) => (i <= greenThreshold ? "var(--clean)" : i > debtThreshold ? "var(--danger)" : "var(--warn)");
  const visible = jobs.filter((j) => j.arrival_slot <= window[1] && (j.finish_slot ?? j.deadline_slot) >= window[0]);
  if (!visible.length) return null;
  return (
    <div className="w-full">
      <div className="relative ml-[188px] h-5 text-[12.5px] text-muted">
        {ticks(window).filter((t) => t < window[1]).map((t) => (
          <span key={t} className="absolute -translate-x-1/2 tabular" style={{ left: x(t) }}>{slotClock(t)}</span>
        ))}
      </div>
      <ul className="flex flex-col gap-1.5">
        {visible.map((j) => (
          <li key={j.id} className="flex items-center gap-3">
            <button
              onClick={() => onSelect?.(j.id)}
              className="w-[176px] shrink-0 truncate text-left text-[14px] text-ink-2 hover:text-ink"
              title={`${j.id} · ${j.name}`}
            >
              <span className={j.job_class === "emergency" ? "text-danger" : ""}>{j.name}</span>
            </button>
            <div className="relative h-8 flex-1 rounded-[5px] bg-raised">
              {/* waiting span: arrival → start (or now) */}
              {(() => {
                const end = j.start_slot ?? Math.min(current, window[1]);
                if (end <= j.arrival_slot) return null;
                return (
                  <div className="absolute top-1/2 h-px -translate-y-1/2 border-t border-dashed border-line-strong"
                    style={{ left: x(Math.max(j.arrival_slot, window[0])), width: w(end - Math.max(j.arrival_slot, window[0])) }} />
                );
              })()}
              {j.planned_start_slot !== null && j.start_slot === null && j.planned_start_slot <= window[1] && (
                <div className="absolute top-0.5 bottom-0.5 rounded-[4px] border border-dashed border-violet"
                  style={{ left: x(j.planned_start_slot), width: w(1) }} title={`Planned start ${slotClock(j.planned_start_slot)}`} />
              )}
              {j.segments.filter((s) => s.slot >= window[0] && s.slot < window[1]).map((s) => (
                <div
                  key={s.slot}
                  className="absolute bottom-0.5 rounded-[3px]"
                  style={{
                    left: `calc(${x(s.slot)} + 1px)`, width: `calc(${w(1)} - 2px)`,
                    height: `calc(${Math.max(s.capacity, 0.12) * 100}% - 4px)`, background: color(s.intensity), opacity: 0.85,
                  }}
                  title={`${slotClock(s.slot)} — ${Math.round(s.capacity * 100)}% capacity at ${num(s.intensity)} gCO₂e/kWh`}
                />
              ))}
              {j.deadline_slot >= window[0] && j.deadline_slot <= window[1] && (
                <div className="absolute top-0 bottom-0 w-px bg-ink-2" style={{ left: x(j.deadline_slot) }}
                  title={`Deadline ${slotClock(j.deadline_slot)}`} />
              )}
              {current >= window[0] && current <= window[1] && (
                <div className="absolute -top-0.5 -bottom-0.5 w-px bg-violet" style={{ left: x(current) }} aria-hidden />
              )}
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-3 ml-[188px]">
        <ChartLegend items={[
          { label: "Ran in green window", color: "var(--clean)", band: true },
          { label: "Ran at moderate intensity", color: "var(--warn)", band: true },
          { label: "Ran above debt threshold", color: "var(--danger)", band: true },
          { label: "Waiting", color: "var(--line-strong)", dashed: true },
          { label: "Planned start", color: "var(--violet)", dashed: true },
        ]} />
        <p className="mt-1.5 text-[13px] text-muted">Bar height shows the capacity share (throttling); the thin vertical tick marks each job's deadline.</p>
      </div>
    </div>
  );
}
