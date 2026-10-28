import type {
  AppMode, ControllerSettings, ControllerView, Curve, Experiment, GanttJob, GridStatus, Job, JobDetail, LedgerEntry,
  LiveStatus, ScenarioStatus, SystemState, TelemetryStatus, TimelinePoint, VerifyResult, WorkloadStat, Decision,
} from "./types";

export const API_BASE: string = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const TOKEN_KEY = "cdc.adminToken";

export function getAdminToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setAdminToken(token: string): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode) — token lasts for this page only */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: any) => {
        const loc = Array.isArray(d.loc) ? d.loc.filter((x: unknown) => x !== "body").join(".") : "";
        return loc ? `${loc}: ${d.msg}` : d.msg;
      })
      .join("; ");
  }
  return "Request failed";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = getAdminToken();
  if (token) headers.set("X-Admin-Token", token);
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "The backend is unreachable. Start it with start-dev.ps1 or check VITE_API_BASE_URL.");
  }
  if (resp.status === 204) return undefined as T;
  const text = await resp.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!resp.ok) {
    const message = body && typeof body === "object" && "detail" in body ? describe(body.detail) : `HTTP ${resp.status}`;
    throw new ApiError(resp.status, resp.status === 401 ? "Admin token required — paste it on the Live Mode page (Admin token box)." : message);
  }
  return body as T;
}

const post = <T,>(path: string, body: unknown = {}) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => request<{ status: string; admin_token_required: boolean; environment: string; database_kind: string }>("/api/health"),
  state: () => request<SystemState>("/api/state"),
  timeline: () => request<{ points: TimelinePoint[] }>("/api/timeline"),
  curve: () => request<Curve>("/api/carbon/curve"),
  gantt: () => request<{ current_slot: number; jobs: GanttJob[] }>("/api/gantt"),
  advance: (slots: number) => post<{ advanced: number; slot: number; at_horizon: boolean }>("/api/sim/advance", { slots }),
  autoplay: (enabled: boolean, speed_ms?: number) => post<{ autoplay: boolean; speed_ms: number }>("/api/sim/autoplay", { enabled, speed_ms }),
  runScenario: (mode: "animated" | "instant", speed_ms?: number) => post<ScenarioStatus>("/api/scenario/run", { mode, speed_ms }),
  scenario: () => request<ScenarioStatus>("/api/scenario/status"),
  loadDemo: () => post<{ loaded: string[] }>("/api/demo/load"),
  loadSamples: () => post<{ loaded: string[] }>("/api/demo/samples"),
  setGrid: (preset: "green" | "coal" | "custom" | "normal", intensity?: number, hours = 2) =>
    post<{ intensity: number | null; until_time: string | null; message: string }>("/api/sim/grid", { preset, intensity, hours }),
  reset: () => post<{ reset: boolean }>("/api/demo/reset", { confirm: "RESET" }),
  jobs: (params: Record<string, string>) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
    return request<Job[]>(`/api/jobs${q ? `?${q}` : ""}`);
  },
  job: (id: string) => request<JobDetail>(`/api/jobs/${encodeURIComponent(id)}`),
  createJob: (body: Record<string, unknown>) => post<{ job: Job; duplicate: boolean }>("/api/jobs", body),
  jobAction: (id: string, action: string, hold_minutes?: number) =>
    post<Job>(`/api/jobs/${encodeURIComponent(id)}/actions`, { action, hold_minutes }),
  decisions: (limit = 100) => request<Decision[]>(`/api/decisions?limit=${limit}`),
  controller: () => request<ControllerView>("/api/controller"),
  updateSettings: (patch: Partial<Record<keyof ControllerSettings, unknown>>) =>
    request<ControllerSettings>("/api/controller/settings", { method: "PUT", body: JSON.stringify(patch) }),
  ledger: () => request<LedgerEntry[]>("/api/ledger"),
  verify: (expected_head?: string) =>
    request<VerifyResult>(`/api/ledger/verify${expected_head ? `?expected_head=${expected_head}` : ""}`),
  tamper: (field: string, seq?: number) =>
    post<{ target_seq: number; field: string; before: string; after: string; original: VerifyResult; tampered_copy: VerifyResult; database_modified: boolean; explanation: string }>(
      "/api/ledger/tamper-demo", { field, seq }),
  workloadStats: () => request<WorkloadStat[]>("/api/stats/workloads"),
  experiments: () => request<Experiment[]>("/api/experiments"),
  experiment: (id: string) => request<Experiment>(`/api/experiments/${id}`),
  experimentDefaults: () => request<Record<string, any>>("/api/experiments/defaults"),
  runExperiment: (body: Record<string, unknown>) => post<Experiment>("/api/experiments", body),
  deleteExperiment: (id: string) => request<void>(`/api/experiments/${id}`, { method: "DELETE" }),
  telemetry: () => request<TelemetryStatus>("/api/telemetry/status"),
  mode: () => request<{ mode: AppMode }>("/api/mode"),
  setMode: (mode: AppMode) => request<{ mode: AppMode }>("/api/mode", { method: "PUT", body: JSON.stringify({ mode }) }),
  liveStatus: () => request<LiveStatus>("/api/live/status"),
  monitoring: (enabled: boolean) => post<{ monitoring: boolean }>("/api/live/monitoring", { enabled }),
  refreshGrid: () => post<GridStatus>("/api/live/grid/refresh"),
};

export const downloadUrl = (path: string) => `${API_BASE}${path}`;
