/** Formatting helpers. Simulated grid time is shown in UTC (the simulated grid's clock);
 *  wall-clock timestamps are shown in the viewer's local time zone. */

export const SLOT_MINUTES = 15;

export function grams(value: number | string | null | undefined, digits = 0): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 10000) return `${(n / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 })} kg`;
  return `${n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })} g`;
}

/** Grams with enough decimals to stay meaningful for tiny live-mode amounts (milligrams). */
export function gramsAuto(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const abs = Math.abs(value);
  return grams(value, abs === 0 ? 0 : abs < 1 ? 3 : abs < 100 ? 1 : 0);
}

export function num(value: number | string | null | undefined, digits = 0): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function intensity(value: number | string | null | undefined): string {
  return value === null || value === undefined ? "—" : `${num(value)} g/kWh`;
}

/* Live mode shows real local clock times; Simulation shows the simulated grid clock (UTC). */
let timeCtx = { live: false, epoch: "", slotMinutes: 15 };
export function setTimeContext(ctx: { live: boolean; epoch: string; slotMinutes: number }): void {
  timeCtx = ctx;
}
export const isLiveTime = () => timeCtx.live;

function localClock(d: Date): string {
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** "07:15" for the sim day, "D+1 07:15" for later days (UTC, the simulated grid clock). */
export function simClock(iso: string | null | undefined, epoch?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (timeCtx.live) return localClock(d);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  if (epoch) {
    const day = Math.floor((d.getTime() - new Date(epoch).getTime()) / 86_400_000);
    if (day > 0) return `D+${day} ${hh}:${mm}`;
  }
  return `${hh}:${mm}`;
}

export function slotClock(slot: number | null | undefined): string {
  if (slot === null || slot === undefined) return "—";
  if (timeCtx.live && timeCtx.epoch) {
    return localClock(new Date(new Date(timeCtx.epoch).getTime() + slot * timeCtx.slotMinutes * 60_000));
  }
  const day = Math.floor((slot * SLOT_MINUTES) / 1440);
  const minutes = (slot * SLOT_MINUTES) % 1440;
  const label = `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
  return day > 0 ? `D+${day} ${label}` : label;
}

export function localTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", day: "numeric", month: "short" });
}

export function minutes(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (Math.abs(value) < 60) return `${Math.round(value)} min`;
  const h = Math.floor(Math.abs(value) / 60);
  const m = Math.round(Math.abs(value) % 60);
  return `${value < 0 ? "−" : ""}${h} h${m ? ` ${m} min` : ""}`;
}

export function shortHash(hash: string | null | undefined, n = 10): string {
  return hash ? `${hash.slice(0, n)}…` : "—";
}

export const ACTION_LABELS: Record<string, string> = {
  ARRIVED: "Arrived",
  START: "Started",
  START_FORCED: "Deadline-forced start",
  EMERGENCY_START: "Emergency start",
  REPAYMENT_START: "Repayment start",
  MANUAL_START: "Operator start",
  DEFER: "Deferred",
  WAIT_CAPACITY: "Waiting for capacity",
  THROTTLE: "Throttled",
  RESTORE: "Capacity restored",
  PAUSE: "Paused",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
  DEADLINE_MISSED: "Deadline missed",
  CONTROLLER_STATE: "Controller state",
  DEBT_CLEARED: "Debt cleared",
  OPERATOR_HOLD: "Operator hold",
  HOLD_RELEASED: "Hold released",
  OPERATOR_RUN_REQUESTED: "Run requested",
  SETTINGS_CHANGED: "Settings changed",
  GRID_CHANGED: "Grid changed",
};

/** Plain grid level relative to the two thresholds. */
export function gridLevel(intensity: number | null | undefined, green: number, debt: number): { label: string; tone: "clean" | "warn" | "danger" | "ink" } {
  if (intensity === null || intensity === undefined) return { label: "Unavailable", tone: "ink" };
  if (intensity <= green) return { label: "Clean electricity", tone: "clean" };
  if (intensity <= debt) return { label: "Moderate", tone: "warn" };
  return { label: "Carbon-intensive", tone: "danger" };
}

export const CLASS_LABELS: Record<string, string> = {
  emergency: "Urgent (runs now)",
  normal: "Normal (can wait a little)",
  background: "Flexible (can wait hours)",
};

export const STATE_LABELS: Record<string, string> = {
  NORMAL: "Normal",
  REPAYING: "Repaying debt",
  THROTTLE_SOFT: "Soft throttle",
  THROTTLE_HARD: "Hard throttle",
  CRITICAL: "Critical",
  CARBON_UNAWARE: "Carbon-unaware",
  THRESHOLD: "Threshold rule",
};

export const POLICY_COLORS: Record<string, string> = {
  fifo: "var(--policy-fifo)",
  threshold: "var(--policy-threshold)",
  debt_reactive: "var(--policy-reactive)",
  debt_predictive: "var(--policy-predictive)",
};

export const POLICY_SHORT: Record<string, string> = {
  fifo: "FIFO",
  threshold: "Threshold",
  debt_reactive: "Debt controller",
  debt_predictive: "Predictive controller",
};
