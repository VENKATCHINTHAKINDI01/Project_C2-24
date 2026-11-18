import { createContext, useContext } from "react";
import { DEFAULT_PREFERENCES, type Preferences } from "./types";

/** The signed-in officer's settings (ADR-0041), for any screen that honours one. */
export const PrefsContext = createContext<Preferences>(DEFAULT_PREFERENCES);
export const usePrefs = (): Preferences => useContext(PrefsContext);

/** "system" follows the computer's own light / dark setting. */
export function resolveTheme(t: Preferences["theme"]): "light" | "dark" {
  if (t !== "system") return t;
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Display settings become attributes on <html>; the stylesheet does the rest. */
export function applyDisplay(p: Preferences): void {
  if (typeof document === "undefined") return;
  const d = document.documentElement.dataset;
  d.theme = resolveTheme(p.theme);
  d.textSize = p.text_size;
  d.density = p.density;
  d.contrast = p.contrast;
  d.motion = p.reduce_motion ? "reduce" : "full";
  d.noteFont = p.note_font;
}
