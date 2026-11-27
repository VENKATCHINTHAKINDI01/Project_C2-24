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

/** Text size is also kept in this browser, so the sign-in page (before any settings are loaded) and
 *  every later page open at the size the person last chose (ADR-0073). */
const SIZE_KEY = "c2.textSize";
export function storedTextSize(): Preferences["text_size"] | null {
  try {
    const v = typeof localStorage !== "undefined" ? localStorage.getItem(SIZE_KEY) : null;
    return v === "normal" || v === "large" || v === "larger" ? v : null;
  } catch { return null; }
}
export function storeTextSize(t: Preferences["text_size"]): void {
  try { localStorage.setItem(SIZE_KEY, t); } catch { /* kept for this visit only */ }
}
