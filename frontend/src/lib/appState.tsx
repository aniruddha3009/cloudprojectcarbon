import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import { setTimeContext } from "./format";
import { usePoll } from "./hooks";
import type { AppMode, SystemState } from "./types";

interface AppState {
  state: SystemState | null;
  error: string | null;
  mode: AppMode | null;
  /** Incremented after every mutation (and on a mode switch) so pages re-fetch their own data. */
  version: number;
  refresh: () => Promise<void>;
  bump: () => void;
}

const Ctx = createContext<AppState | null>(null);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [version, setVersion] = useState(0);
  const [fast, setFast] = useState(false);
  const lastMode = useRef<AppMode | null>(null);
  const { data, error, refresh } = usePoll(async () => {
    const s = await api.state();
    setTimeContext({ live: s.mode === "live", epoch: s.clock.epoch, slotMinutes: s.clock.slot_minutes });
    setFast(s.clock.autoplay);
    if (lastMode.current !== null && lastMode.current !== s.mode) setVersion((v) => v + 1);
    lastMode.current = s.mode;
    return s;
  }, fast ? 1500 : 3000);
  const bump = useCallback(() => {
    setVersion((v) => v + 1);
    void refresh();
  }, [refresh]);
  return (
    <Ctx.Provider value={{ state: data, error, mode: data?.mode ?? null, version, refresh, bump }}>{children}</Ctx.Provider>
  );
}

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp outside provider");
  return ctx;
}

/** Interval for page-level polling: fast while the simulation plays or Live monitoring runs. */
export function usePollInterval(): number {
  const { state } = useApp();
  return state?.clock.autoplay ? (state.mode === "live" ? 2500 : 1000) : 4000;
}
