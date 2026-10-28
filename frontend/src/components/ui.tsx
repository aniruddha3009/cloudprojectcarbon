import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, animate, motion, useMotionValue } from "motion/react";
import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle } from "lucide-react";
import type { JobClass, JobState } from "../lib/types";
import { Swap } from "./motion";

export const EASE = [0.16, 1, 0.3, 1] as const;

export function cx(...xs: (string | false | null | undefined)[]) {
  return xs.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ Button */
type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  variant = "secondary", size = "md", busy = false, icon, children, className = "", ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg"; busy?: boolean; icon?: ReactNode }) {
  const iconOnly = !children;
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      className={cx(
        "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-full font-semibold disabled:cursor-not-allowed disabled:opacity-40",
        size === "sm" ? "h-8 px-3.5 text-[12.5px]" : size === "lg" ? "h-12 px-6 text-[15px]" : "h-10 px-5 text-[13.5px]",
        iconOnly && (size === "sm" ? "w-8 !px-0" : "w-10 !px-0"),
        variant === "primary" && "bg-ink text-on-ink shadow-[0_1px_2px_rgb(12_10_9/0.2),0_6px_16px_-6px_rgb(12_10_9/0.45)] hover:-translate-y-px hover:bg-accent-hover hover:shadow-[0_2px_4px_rgb(12_10_9/0.2),0_10px_24px_-8px_rgb(12_10_9/0.5)]",
        variant === "secondary" && "border border-line-strong bg-panel text-ink hover:-translate-y-px hover:border-faint hover:shadow-[0_6px_16px_-8px_rgb(12_10_9/0.2)]",
        variant === "ghost" && "text-ink-2 hover:bg-stone hover:text-ink",
        variant === "danger" && "border border-bad/25 bg-bad-soft text-bad hover:-translate-y-px hover:bg-bad hover:text-on-ink",
        className,
      )}
    >
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ Badges */
type Tone = "neutral" | "ok" | "warn" | "bad" | "accent";
const BADGE: Record<Tone, string> = {
  neutral: "bg-stone text-muted border-line",
  ok: "bg-ok-soft text-ok border-ok/25",
  warn: "bg-warn-soft text-warn border-warn/25",
  bad: "bg-bad-soft text-bad border-bad/25",
  accent: "bg-lav-soft text-lav-ink border-lav-line",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={cx("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11.5px] font-semibold", BADGE[tone], className)}>{children}</span>;
}

const STATE_TONE: Record<JobState, Tone> = {
  pending: "neutral", queued: "neutral", deferred: "accent", running: "neutral",
  paused: "warn", completed: "ok", failed: "bad", cancelled: "neutral",
};

export function StateBadge({ state }: { state: JobState }) {
  return (
    <Badge tone={STATE_TONE[state]} className={state === "running" ? "!text-ink" : ""}>
      {state === "running" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink" aria-hidden />}
      {state.charAt(0).toUpperCase() + state.slice(1)}
    </Badge>
  );
}

const STATUS_TONE: Record<string, Tone> = {
  "Running": "neutral", "Waiting": "neutral", "Scheduled for later": "accent", "Paused": "warn",
  "Completed": "ok", "Failed": "bad", "Cancelled": "neutral", "Not arrived yet": "neutral",
};

/** Plain status label from the backend (Running, Waiting, Scheduled for later, Paused, Completed, Failed…). */
export function StatusBadge({ label }: { label: string }) {
  return (
    <Badge tone={STATUS_TONE[label] ?? "neutral"} className={label === "Running" ? "!text-ink" : ""}>
      {label === "Running" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink" aria-hidden />}
      {label}
    </Badge>
  );
}

/** Collapsed-by-default section for technical material that is not part of the normal demo flow. */
export function Details({ summary = "Technical details", children, className }: { summary?: string; children: ReactNode; className?: string }) {
  return (
    <details className={cx("group rounded-[22px] border border-line bg-panel", className)}>
      <summary className="flex cursor-pointer list-none items-center gap-2 px-6 py-4 text-[14px] font-semibold text-ink-2 hover:text-ink">
        <span className="inline-block transition-transform group-open:rotate-90" aria-hidden>›</span>
        {summary}
      </summary>
      <div className="flex flex-col gap-6 px-6 pb-6">{children}</div>
    </details>
  );
}

const CLASS_TONE: Record<JobClass, Tone> = { emergency: "bad", normal: "neutral", background: "neutral" };

export function ClassBadge({ jobClass }: { jobClass: JobClass }) {
  const label = { emergency: "Urgent", normal: "Normal", background: "Flexible" }[jobClass];
  return <Badge tone={CLASS_TONE[jobClass]} className={jobClass === "background" ? "bg-panel" : ""}>{label}</Badge>;
}

export function SourceTag({ source }: { source: string }) {
  const live = source.startsWith("LIVE") || source === "MEASURED";
  const manual = source === "MANUAL_OVERRIDE";
  return (
    <Badge tone={live ? "ok" : manual ? "warn" : "neutral"}>
      <span className={cx("h-1.5 w-1.5 rounded-full", live ? "bg-ok" : manual ? "bg-warn" : "bg-faint")} aria-hidden />
      {source.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase())}
    </Badge>
  );
}

/* ------------------------------------------------------------------ Panels */
export function Panel({ title, sub, actions, children, className = "", bodyClass }: {
  title?: ReactNode; sub?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={cx("vz-panel flex min-h-0 flex-col rounded-[22px] border border-line bg-panel", className)}>
      {(title || actions) && (
        <header className="flex min-h-14 shrink-0 flex-wrap items-center gap-3 px-6 pt-5 pb-3">
          <div className="min-w-0">
            {title && <h2 className="text-[16px] font-semibold tracking-tight text-ink">{title}</h2>}
            {sub && <p className="mt-1 text-[13px] text-muted">{sub}</p>}
          </div>
          {actions && <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx("min-h-0 flex-1", bodyClass ?? "px-6 pb-6 pt-2")}>{children}</div>
    </section>
  );
}

/** Large page heading with pastel atmosphere. */
export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="relative mb-4 pb-2 pt-10">
      <div className="relative z-10 flex flex-wrap items-end gap-6">
        <div className="max-w-3xl">
          {eyebrow && (
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: EASE }} className="mb-4 inline-flex items-center gap-2 rounded-full border border-line bg-glass px-3 py-1 text-[12px] font-semibold text-ink-2 backdrop-blur">
              <span className="vz-orb h-3 w-3" /> {eyebrow}
            </motion.div>
          )}
          <motion.h1 initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, ease: EASE, delay: 0.05 }} className="font-display text-[34px] font-light leading-[1.1] text-ink lg:text-[40px]">
            {title}
          </motion.h1>
          {description && (
            <motion.p initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, ease: EASE, delay: 0.12 }} className="mt-3 max-w-2xl text-[15px] leading-relaxed text-muted">
              {description}
            </motion.p>
          )}
        </div>
        {actions && <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.8, delay: 0.2 }} className="ml-auto flex flex-wrap items-center gap-2">{actions}</motion.div>}
      </div>
    </div>
  );
}

/** Fades and lifts its content into view once it scrolls on screen. */
export function Reveal({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 36 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.08, margin: "0px 0px -60px 0px" }}
      transition={{ duration: 0.9, ease: EASE, delay }}
    >
      {children}
    </motion.div>
  );
}

/** Counts smoothly to a new value when the backend reports a change. */
export function AnimatedNumber({ value, format }: { value: number; format: (n: number) => string }) {
  const mv = useMotionValue(value);
  const [text, setText] = useState(() => format(value));
  useEffect(() => {
    const controls = animate(mv, value, { duration: 0.7, ease: EASE, onUpdate: (v) => setText(format(v)) });
    return () => controls.stop();
  }, [value, mv, format]);
  return <>{text}</>;
}

export function EmptyState({ title, body, action }: { title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex min-h-[220px] flex-col items-center justify-center gap-3 p-10 text-center">
      <span className="vz-orb h-10 w-10 opacity-80" />
      <div className="text-[15px] font-semibold text-ink">{title}</div>
      {body && <div className="max-w-md text-[13.5px] leading-relaxed text-muted">{body}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} role="alert"
      className="flex items-start gap-3 rounded-2xl border border-bad/25 bg-bad-soft px-5 py-4 text-[13.5px] font-medium">
      <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-bad" aria-hidden />
      <div className="flex-1 text-ink">{message}</div>
      {onRetry && <Button size="sm" variant="ghost" onClick={onRetry}>Retry</Button>}
    </motion.div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-8 text-[13.5px] font-medium text-muted" role="status">
      <span className="vz-orb h-5 w-5" aria-hidden /> {label}…
    </div>
  );
}

export function KV({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-line py-2.5 last:border-0">
      <dt className="text-[13px] text-muted" title={hint}>{label}</dt>
      <dd className="text-right text-[13px] font-medium tabular-nums text-ink">{children}</dd>
    </div>
  );
}

/** Pill segmented control; the selection thumb glides between options. */
export function Segmented<T extends string>({ value, options, onChange, label, size = "md" }: {
  value: T; options: { value: T; label: ReactNode; title?: string }[]; onChange: (v: T) => void; label: string; size?: "sm" | "md";
}) {
  const id = useId();
  return (
    <div className="relative inline-flex rounded-full border border-line bg-stone p-1" role="radiogroup" aria-label={label}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            role="radio"
            aria-checked={on}
            title={o.title}
            onClick={() => onChange(o.value)}
            className={cx("relative rounded-full font-semibold", size === "sm" ? "px-3 py-1 text-[12px]" : "px-3.5 py-1.5 text-[13px]", on ? "text-ink" : "text-muted hover:text-ink")}
          >
            {on && (
              <motion.span layoutId={`seg-${id}`} className="absolute inset-0 rounded-full bg-panel shadow-[0_1px_2px_rgb(12_10_9/0.08),0_3px_10px_-3px_rgb(12_10_9/0.15)]"
                transition={{ type: "spring", stiffness: 420, damping: 36 }} />
            )}
            <span className="relative">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Section switcher: the same gliding pill control, sized for page sections. */
export function Tabs<T extends string>({ value, onChange, tabs }: {
  value: T; onChange: (v: T) => void; tabs: { value: T; label: string; count?: number }[];
}) {
  const id = useId();
  return (
    <div className="flex overflow-x-auto pb-1">
      <div role="tablist" className="relative inline-flex rounded-full border border-line bg-stone p-1">
        {tabs.map((t) => {
          const on = value === t.value;
          return (
            <button key={t.value} role="tab" aria-selected={on} onClick={() => onChange(t.value)}
              className={cx("relative whitespace-nowrap rounded-full px-4 py-2 text-[13.5px] font-semibold", on ? "text-ink" : "text-muted hover:text-ink")}>
              {on && (
                <motion.span layoutId={`tab-${id}`} className="absolute inset-0 rounded-full bg-panel shadow-[0_1px_2px_rgb(12_10_9/0.08),0_3px_10px_-3px_rgb(12_10_9/0.15)]"
                  transition={{ type: "spring", stiffness: 420, damping: 36 }} />
              )}
              <span className="relative">{t.label}</span>
              {t.count !== undefined && <span className="relative ml-2 font-mono text-[11.5px] font-medium text-faint">{t.count}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function TabPanel({ id, children }: { id: string; children: ReactNode }) {
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div key={id} initial={{ opacity: 0, y: 14, filter: "blur(4px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
        exit={{ opacity: 0, y: -8, filter: "blur(4px)" }} transition={{ duration: 0.45, ease: EASE }}>
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

/** Metric tile: muted label, large light display value, faint hint (VizReg "Metric" in a card). */
export function Stat({ label, value, hint, tone = "ink" }: {
  label: string; value: ReactNode; hint?: ReactNode; tone?: "ink" | "clean" | "violet" | "warn" | "danger";
}) {
  const color = { ink: "text-ink", clean: "text-ok", violet: "text-lav-ink", warn: "text-warn", danger: "text-bad" }[tone];
  return (
    <div className="vz-panel rounded-[22px] border border-line bg-panel px-6 py-5">
      <div className="text-[12px] font-semibold text-muted">{label}</div>
      <div className={cx("mt-2 truncate font-display text-[34px] font-light leading-none tracking-tight", color)}>
        <Swap k={typeof value === "string" || typeof value === "number" ? value : JSON.stringify(String(value))} inline y={8}>{value}</Swap>
      </div>
      {hint && <div className="mt-2 text-[12.5px] font-medium leading-snug text-faint">{hint}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ Dialog */
export function ConfirmDialog({ open, title, body, confirmLabel, danger, onConfirm, onCancel, busy }: {
  open: boolean; title: string; body: ReactNode; confirmLabel: string; danger?: boolean; busy?: boolean;
  onConfirm: () => void; onCancel: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const t = window.setTimeout(() => ref.current?.querySelector<HTMLButtonElement>("button[data-autofocus]")?.focus(), 30);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("keydown", onKey);
      prev?.focus();
    };
  }, [open, onCancel]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 flex items-center justify-center p-4 backdrop-blur-sm" style={{ background: "var(--overlay)" }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.25 }}
          onMouseDown={onCancel}>
          <motion.div
            ref={ref}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            className="vz-raised w-full max-w-md rounded-[28px] border border-line bg-panel p-7"
            initial={{ opacity: 0, scale: 0.95, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97, y: 6 }}
            transition={{ duration: 0.4, ease: EASE }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 id="confirm-title" className="font-display text-[24px] font-light leading-tight">{title}</h2>
            <div className="mt-3 text-[14px] leading-relaxed text-muted">{body}</div>
            <div className="mt-7 flex justify-end gap-2">
              <Button variant="ghost" onClick={onCancel} data-autofocus>Keep current data</Button>
              <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} busy={busy}>{confirmLabel}</Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function Drawer({ open, onClose, title, children, width = "max-w-2xl" }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; width?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-40 flex justify-end p-3 backdrop-blur-[2px]" style={{ background: "var(--overlay)" }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.3 }}
          onMouseDown={onClose}>
          <motion.aside
            role="dialog"
            aria-modal="true"
            data-lenis-prevent
            className={cx("vz-raised flex h-full w-full flex-col overflow-hidden rounded-[28px] border border-line bg-panel", width)}
            initial={{ x: 60, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 60, opacity: 0 }}
            transition={{ duration: 0.55, ease: EASE }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <header className="flex items-start justify-between gap-4 border-b border-line px-7 py-5">
              <div className="min-w-0">{title}</div>
              <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close panel" icon={<X className="h-4 w-4" />} />
            </header>
            <div className="flex-1 overflow-y-auto px-7 py-6">{children}</div>
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/* ------------------------------------------------------------------ Toasts */
type ToastTone = "success" | "error" | "info" | "warning";
interface Toast { id: number; tone: ToastTone; message: string }
const ToastCtx = createContext<(tone: ToastTone, message: string) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((tone: ToastTone, message: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, tone, message }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "error" ? 7000 : 4000);
  }, []);
  const icons = {
    success: <CheckCircle2 className="h-4 w-4 text-ok" aria-hidden />,
    error: <XCircle className="h-4 w-4 text-bad" aria-hidden />,
    warning: <AlertTriangle className="h-4 w-4 text-warn" aria-hidden />,
    info: <Info className="h-4 w-4 text-lav-ink" aria-hidden />,
  };
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-6 right-6 z-[60] flex w-[min(380px,calc(100vw-3rem))] flex-col gap-2" aria-live="polite">
        <AnimatePresence initial={false}>
          {toasts.map((t) => (
            <motion.div key={t.id} layout
              initial={{ opacity: 0, y: 14, filter: "blur(4px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, x: 24, filter: "blur(4px)", transition: { duration: 0.2 } }} transition={{ duration: 0.45, ease: EASE }}
              className="vz-raised pointer-events-auto flex items-start gap-3 rounded-2xl border border-line bg-glass px-4 py-3 text-[13.5px] font-medium backdrop-blur-xl">
              <span className="mt-0.5">{icons[t.tone]}</span>
              <span className="flex-1 text-ink">{t.message}</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);
