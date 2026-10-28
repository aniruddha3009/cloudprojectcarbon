import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export type ThemeName = "light" | "grey" | "dark";
export const THEMES: ThemeName[] = ["light", "grey", "dark"];
export const THEME_KEY = "cdc.theme.v2"; // v2: dark is the new default, so earlier saved choices are ignored

interface ThemeValue {
  theme: ThemeName;
  setTheme: (t: ThemeName) => void;
}

const Ctx = createContext<ThemeValue>({ theme: "dark", setTheme: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeName>("dark");

  useEffect(() => {
    const t = document.documentElement.dataset.theme as ThemeName | undefined;
    if (t && THEMES.includes(t)) setThemeState(t);
  }, []);

  const setTheme = useCallback((t: ThemeName) => {
    const root = document.documentElement;
    // Briefly enable colour transitions everywhere so the switch cross-fades instead of snapping.
    root.classList.add("theme-transition");
    root.dataset.theme = t;
    window.setTimeout(() => root.classList.remove("theme-transition"), 450);
    try {
      localStorage.setItem(THEME_KEY, t);
    } catch {
      /* storage unavailable */
    }
    setThemeState(t);
  }, []);

  return <Ctx.Provider value={{ theme, setTheme }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);

/** Applies the saved theme before first paint (avoids a flash). */
export function bootTheme(): void {
  try {
    const t = localStorage.getItem(THEME_KEY);
    document.documentElement.dataset.theme = t === "grey" || t === "dark" || t === "light" ? t : "dark";
  } catch {
    document.documentElement.dataset.theme = "dark";
  }
}
