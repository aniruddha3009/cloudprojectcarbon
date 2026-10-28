import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import Lenis from "lenis";

interface ScrollApi {
  /** Smoothly scroll the main area to an element (or a y offset). */
  scrollTo: (target: HTMLElement | number, opts?: { offset?: number; immediate?: boolean }) => void;
  /** The scrolling element (for IntersectionObserver roots etc.). */
  root: HTMLElement | null;
}

const Ctx = createContext<ScrollApi>({ scrollTo: () => {}, root: null });

/**
 * Wraps the main content area in a Lenis smooth-scroll container. Nested scroll areas opt out with
 * `data-lenis-prevent`, so tables and long lists keep native scrolling.
 */
export function SmoothScroll({ children, className, resetKey }: { children: ReactNode; className?: string; resetKey?: string }) {
  const wrapper = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const lenis = useRef<Lenis | null>(null);
  const [root, setRoot] = useState<HTMLElement | null>(null);

  useEffect(() => {
    if (!wrapper.current || !content.current) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const l = new Lenis({ wrapper: wrapper.current, content: content.current, lerp: reduce ? 1 : 0.09, smoothWheel: !reduce, wheelMultiplier: 0.95 });
    lenis.current = l;
    setRoot(wrapper.current);
    let id = 0;
    const raf = (t: number) => {
      l.raf(t);
      id = requestAnimationFrame(raf);
    };
    id = requestAnimationFrame(raf);
    return () => {
      cancelAnimationFrame(id);
      l.destroy();
      lenis.current = null;
    };
  }, []);

  // Jump to the top when the page changes.
  useEffect(() => {
    lenis.current?.scrollTo(0, { immediate: true });
  }, [resetKey]);

  const api: ScrollApi = {
    root,
    scrollTo: (target, opts) => {
      if (lenis.current) lenis.current.scrollTo(target, { offset: opts?.offset ?? 0, immediate: opts?.immediate, duration: 1.1, easing: (t) => 1 - Math.pow(1 - t, 4) });
      else if (typeof target !== "number") target.scrollIntoView({ behavior: "smooth", block: "start" });
    },
  };

  return (
    <Ctx.Provider value={api}>
      <div ref={wrapper} className={className}>
        <div ref={content}>{children}</div>
      </div>
    </Ctx.Provider>
  );
}

export const useSmoothScroll = () => useContext(Ctx);
