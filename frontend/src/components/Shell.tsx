import { useState, type ReactElement, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { api } from "../lib/api";
import { useApp } from "../lib/appState";
import { STATE_LABELS, num } from "../lib/format";
import { useTheme, type ThemeName } from "../lib/theme";
import { SmoothScroll } from "../lib/smoothScroll";
import type { AppMode } from "../lib/types";
import {
  IconChart, IconGauge, IconHalf, IconHome, IconLedger, IconList, IconMoon, IconPause, IconPlay, IconSignal, IconStep, IconSun,
} from "./icons";
import { Button, EASE, Segmented, useToast } from "./ui";

export const ROUTES = [
  { id: "overview", label: "Overview", icon: IconHome },
  { id: "queue", label: "Process Queue", icon: IconList },
  { id: "scheduler", label: "Scheduler", icon: IconGauge },
  { id: "experiments", label: "Experiments", icon: IconChart },
  { id: "history", label: "History", icon: IconLedger },
  { id: "live", label: "Live Mode", icon: IconSignal },
] as const;

const TONE: Record<string, { cls: string; dot: string }> = {
  neutral: { cls: "text-muted bg-glass border-line", dot: "bg-faint" },
  ok: { cls: "text-ok bg-ok-soft/90 border-ok/25", dot: "bg-ok" },
  warn: { cls: "text-warn bg-warn-soft/90 border-warn/25", dot: "bg-warn" },
  bad: { cls: "text-bad bg-bad-soft/90 border-bad/25", dot: "bg-bad" },
  accent: { cls: "text-lav-ink bg-lav-soft/90 border-lav-line", dot: "bg-lav-ink" },
};

const THEME_OPTIONS: { value: ThemeName; label: string; Icon: (p: { className?: string }) => ReactElement }[] = [
  { value: "dark", label: "Dark", Icon: IconMoon },
  { value: "grey", label: "Grey", Icon: IconHalf },
  { value: "light", label: "Light", Icon: IconSun },
];

function ThemeSwitch() {
  const { theme, setTheme } = useTheme();
  return (
    <div role="radiogroup" aria-label="Colour theme" className="flex items-center rounded-full border border-line bg-glass p-[3px] backdrop-blur">
      {THEME_OPTIONS.map(({ value, label, Icon }) => {
        const on = theme === value;
        return (
          <button key={value} role="radio" aria-checked={on} aria-label={`${label} theme`} title={`${label} theme`} onClick={() => setTheme(value)}
            className={`relative flex h-7 w-7 items-center justify-center rounded-full ${on ? "text-on-ink" : "text-muted hover:text-ink"}`}>
            {on && <motion.span layoutId="theme-pill" className="absolute inset-0 rounded-full bg-ink" transition={{ type: "spring", stiffness: 500, damping: 35 }} />}
            <span className="relative"><Icon className="h-[15px] w-[15px]" /></span>
          </button>
        );
      })}
    </div>
  );
}

function ModeSwitch() {
  const { mode, bump } = useApp();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!mode) return null;
  const change = async (m: AppMode) => {
    if (m === mode || busy) return;
    setBusy(true);
    try {
      await api.setMode(m);
      toast("info", m === "live" ? "Live mode: press Start monitoring to collect real data." : "Simulation mode: repeatable, simulated data.");
      bump();
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Segmented<AppMode> label="Operating mode" size="sm" value={mode} onChange={change}
      options={[{ value: "simulation", label: "Simulation", title: "Controlled, repeatable demonstration (simulated data)" },
        { value: "live", label: "Live", title: "Real laptop telemetry and real grid readings" }]} />
  );
}

function SimControls() {
  const { state, bump } = useApp();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const atHorizon = state ? state.clock.slot >= state.clock.horizon_slot : false;
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
  if (state?.mode === "live") {
    const on = state.clock.autoplay;
    return (
      <Button size="sm" variant={on ? "secondary" : "primary"} icon={on ? <IconPause className="h-4 w-4" /> : <IconPlay className="h-4 w-4" />}
        busy={busy === "mon"} onClick={() => act("mon", () => api.monitoring(!on), on ? "Monitoring stopped. Managed workloads are paused." : "Monitoring started.")}>
        {on ? "Stop monitoring" : "Start monitoring"}
      </Button>
    );
  }
  return (
    <>
      <Button size="sm" variant="ghost" icon={<IconStep className="h-4 w-4" />} disabled={!state || state.clock.autoplay || atHorizon}
        busy={busy === "step"} onClick={() => act("step", () => api.advance(1))} title="Advance the simulation by 15 minutes">Step 15 min</Button>
      <Button size="sm" icon={state?.clock.autoplay ? <IconPause className="h-4 w-4" /> : <IconPlay className="h-4 w-4" />}
        disabled={!state || (!state.clock.autoplay && atHorizon)} busy={busy === "play"}
        onClick={() => act("play", () => api.autoplay(!state!.clock.autoplay))}>
        {state?.clock.autoplay ? "Pause" : "Play"}
      </Button>
    </>
  );
}

function SourceRow({ label, ok, text }: { label: string; ok: boolean | null; text: string }) {
  return (
    <div>
      <div className="text-faint">{label}</div>
      <div className="mt-0.5 flex items-center gap-2 font-medium text-ink-2">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${ok === null ? "bg-faint" : ok ? "bg-ok" : "bg-warn"}`} aria-hidden />
        <span className="truncate">{text}</span>
      </div>
    </div>
  );
}

function DataSources() {
  const { state } = useApp();
  if (!state) return null;
  if (state.mode !== "live" || !state.live) {
    return (
      <div className="space-y-3">
        <SourceRow label="Grid data" ok={null} text="Simulated" />
        <SourceRow label="Energy" ok={null} text="Estimated Energy" />
      </div>
    );
  }
  const g = state.live.grid;
  const gridText = { ok: "Live Grid Data", stale: "Live Grid Data (old)",
    error: g.intensity !== null ? "Last reading (fetch failed)" : "Unavailable",
    waiting: "Waiting for a reading", not_configured: "Unavailable (no API key)" }[g.state];
  return (
    <div className="space-y-3">
      <SourceRow label="Grid data" ok={g.state === "ok"} text={gridText} />
      <SourceRow label="Energy" ok={state.live.energy_meter.available} text={state.live.energy_meter.available ? "Estimated Energy (measured CPU power)" : "Estimated Energy (CPU time)"} />
      <SourceRow label="Processes" ok={state.live.monitoring} text={state.live.monitoring ? "Live Process Monitoring" : "Monitoring off"} />
    </div>
  );
}

export function AppShell({ route, onNavigate, children }: { route: string; onNavigate: (r: string) => void; children: ReactNode }) {
  const { state, error } = useApp();
  const activeIdx = Math.max(0, ROUTES.findIndex((r) => r.id === route));
  const active = ROUTES[activeIdx];
  const c = state?.carbon;
  const live = state?.mode === "live";
  const status = !state
    ? (error ? { tone: "bad", text: "Backend unreachable" } : null)
    : live
      ? (state.clock.autoplay ? { tone: "ok", text: "Monitoring" } : { tone: "neutral", text: "Monitoring off" })
      : state.controller.inversion_active
        ? { tone: "accent", text: STATE_LABELS[state.controller.state] ?? state.controller.state }
        : state.clock.autoplay ? { tone: "neutral", text: "Running" } : { tone: "ok", text: STATE_LABELS[state.controller.state] ?? state.controller.state };
  const intensityTone = !c || c.intensity === null ? "text-muted" : c.green ? "text-ok" : c.intensity > c.debt_threshold ? "text-bad" : "text-warn";

  return (
    <div className="flex h-screen min-h-0 overflow-hidden bg-page">
      <aside className="flex w-[64px] shrink-0 flex-col border-r border-line bg-page lg:w-[232px]">
        <a href="#/overview" onClick={(e) => { e.preventDefault(); onNavigate("overview"); }} className="group flex h-16 items-center gap-3 px-5">
          <span className="vz-orb h-7 w-7 shrink-0 transition-transform duration-500 group-hover:scale-110" aria-hidden />
          <span className="hidden flex-col leading-tight lg:flex">
            <span className="font-display text-[19px] font-medium">CarbonDebt</span>
          </span>
        </a>
        <nav className="flex flex-1 flex-col gap-1 px-3 pt-4" aria-label="Main">
          {ROUTES.map((n, i) => {
            const on = i === activeIdx;
            const Icon = n.icon;
            return (
              <a key={n.id} href={`#/${n.id}`} onClick={(e) => { e.preventDefault(); onNavigate(n.id); }}
                aria-current={on ? "page" : undefined} title={n.label}
                className={`relative flex items-center gap-3 rounded-full px-3.5 py-2.5 text-[14px] ${on ? "font-semibold text-ink" : "font-medium text-muted hover:text-ink"}`}>
                {on && (
                  <motion.span layoutId="nav-pill" className="absolute inset-0 rounded-full bg-stone ring-1 ring-line"
                    transition={{ duration: 0.45, ease: EASE }} />
                )}
                <Icon className="relative h-[18px] w-[18px] shrink-0" />
                <span className="relative hidden lg:inline">{n.label}</span>
              </a>
            );
          })}
        </nav>
        <div className="m-3 hidden rounded-2xl border border-line bg-panel p-4 text-[12px] leading-relaxed lg:block">
          <div className="mb-3 text-[12.5px] font-semibold text-ink">{live ? "Live mode" : "Simulation mode"}</div>
          <DataSources />
        </div>
      </aside>

      <div className="relative flex min-w-0 flex-1 flex-col">
        <header className="absolute inset-x-0 top-0 z-30 flex h-16 items-center gap-3 border-b border-line/70 bg-page/80 px-6 backdrop-blur-xl lg:px-8">
          <motion.h1 key={active.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: EASE }} className="text-[15px] font-semibold">
            {active.label}
          </motion.h1>
          <ModeSwitch />
          {state && c && (
            <span className="hidden min-w-0 items-center gap-3 xl:flex">
              <span className="rounded-full border border-line bg-panel px-2.5 py-0.5 font-mono text-[12px] font-medium text-ink-2"
                title={live ? "Your local time" : "Simulated grid clock (UTC)"}>
                {live ? new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : `${state.clock.label} UTC`}
              </span>
              <span className="text-[13.5px] font-medium text-muted" title={live ? "Latest real reading (India Energy Atlas)" : "Simulated grid intensity"}>
                {c.intensity === null ? "No grid reading" : <><span className={`font-semibold ${intensityTone}`}>{num(c.intensity)}</span> gCO₂e/kWh</>}
              </span>
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <AnimatePresence mode="popLayout" initial={false}>
              {status && (
                <motion.span key={status.tone + status.text} layout
                  initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 6 }} transition={{ duration: 0.3, ease: EASE }}
                  className={`hidden items-center gap-2 rounded-full border px-3 py-1 text-[12.5px] font-semibold backdrop-blur 2xl:inline-flex ${TONE[status.tone].cls}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${TONE[status.tone].dot}`} />
                  {status.text}
                </motion.span>
              )}
            </AnimatePresence>
            <SimControls />
            <ThemeSwitch />
          </div>
        </header>
        <SmoothScroll className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto" resetKey={route}>
          <motion.div key={route} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: EASE }} className="min-h-full pt-16">
            {children}
          </motion.div>
        </SmoothScroll>
      </div>
    </div>
  );
}
