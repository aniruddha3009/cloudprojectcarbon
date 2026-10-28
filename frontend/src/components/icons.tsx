import type { ReactNode } from "react";

// Simple 1.6px line icons (24×24 grid), same style as the VizReg project.
type P = { className?: string };
const base = (path: ReactNode, { className = "h-4 w-4" }: P) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
    {path}
  </svg>
);

export const IconHome = (p: P) => base(<><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V21h14V9.5" /><path d="M10 21v-6h4v6" /></>, p);
export const IconList = (p: P) => base(<><path d="M9 6h11M9 12h11M9 18h11" /><circle cx="4.5" cy="6" r="1" /><circle cx="4.5" cy="12" r="1" /><circle cx="4.5" cy="18" r="1" /></>, p);
export const IconGauge = (p: P) => base(<><path d="M4.5 17.5a8.5 8.5 0 1 1 15 0" /><path d="m12 13 4-4" /><circle cx="12" cy="13" r="1.2" /></>, p);
export const IconLedger = (p: P) => base(<><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></>, p);
export const IconChart = (p: P) => base(<><path d="M4 20V4" /><path d="M4 20h16" /><path d="M8 16v-5" /><path d="M12 16V8" /><path d="M16 16v-3" /></>, p);
export const IconSignal = (p: P) => base(<><path d="M3 12h3l3-7 4 14 3-7h5" /></>, p);
export const IconPlay = (p: P) => base(<path d="M7 5v14l11-7z" />, p);
export const IconPause = (p: P) => base(<><path d="M8 5v14" /><path d="M16 5v14" /></>, p);
export const IconNext = (p: P) => base(<path d="m9 6 6 6-6 6" />, p);
export const IconStep = (p: P) => base(<><path d="M6 5v14l9-7z" /><path d="M18 5v14" /></>, p);
export const IconArrowRight = (p: P) => base(<><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>, p);
export const IconSun = (p: P) => base(<><circle cx="12" cy="12" r="4" /><path d="M12 3v1.5M12 19.5V21M3 12h1.5M19.5 12H21M5.6 5.6l1.1 1.1M17.3 17.3l1.1 1.1M5.6 18.4l1.1-1.1M17.3 6.7l1.1-1.1" /></>, p);
export const IconMoon = (p: P) => base(<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />, p);
export const IconHalf = (p: P) => base(<><circle cx="12" cy="12" r="8.5" /><path d="M12 3.5v17a8.5 8.5 0 0 0 0-17z" fill="currentColor" stroke="none" /></>, p);
