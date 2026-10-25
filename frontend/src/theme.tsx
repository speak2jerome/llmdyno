// Light / dark / system theme, persisted in settings (server) with a local cache for first paint.
import { createContext, useContext, useEffect, useMemo, useState } from "react";

type Pref = "light" | "dark" | "system";
const Ctx = createContext<{ pref: Pref; resolved: "light" | "dark"; setPref: (p: Pref) => void }>({
  pref: "system", resolved: "light", setPref: () => undefined,
});

function systemDark() {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [pref, setPrefState] = useState<Pref>(() => {
    // ?theme=dark|light forces a theme for this page load (screenshots, docs links) without saving it
    const forced = new URLSearchParams(location.search).get("theme");
    if (forced === "dark" || forced === "light") return forced;
    try {
      return (localStorage.getItem("llmdyno-theme") as Pref) || "system";
    } catch {
      return "system";
    }
  });
  const [sys, setSys] = useState(systemDark());
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const h = () => setSys(mq.matches);
    mq?.addEventListener("change", h);
    return () => mq?.removeEventListener("change", h);
  }, []);
  const resolved: "light" | "dark" = pref === "system" ? (sys ? "dark" : "light") : pref;
  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);
  const value = useMemo(() => ({
    pref, resolved,
    setPref: (p: Pref) => {
      setPrefState(p);
      try {
        localStorage.setItem("llmdyno-theme", p);
      } catch {
        /* storage unavailable */
      }
      fetch("/api/settings", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ theme: p }) }).catch(() => undefined);
    },
  }), [pref, resolved]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
