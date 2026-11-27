import { useSyncExternalStore } from "react";
import { ROWS } from "./i18n-dict";

/** Screen language (ADR-0073): English, Telugu or Hindi. Fixed screen text is swapped in the page by
 *  one translator (below); names, numbers, dates, notes, orders and AI answers are left as written. */
export type Lang = "en" | "te" | "hi";
export const LANGS: { code: Lang; label: string; name: string }[] = [
  { code: "en", label: "English", name: "English" },
  { code: "te", label: "తెలుగు", name: "Telugu" },
  { code: "hi", label: "हिन्दी", name: "Hindi" },
];
const KEY = "c2.lang";
const HTML_LANG: Record<Lang, string> = { en: "en-IN", te: "te", hi: "hi" };

const EXACT = new Map<string, readonly [string, string]>(ROWS.map(([en, te, hi]) => [en, [te, hi]]));
const pick = (pair: readonly [string, string], lang: Lang) => (lang === "te" ? pair[0] : pair[1]);

function word(s: string, lang: Lang): string | null {
  const p = EXACT.get(s);
  return p ? pick(p, lang) : null;
}

type Pattern = [RegExp, (m: RegExpExecArray, lang: Lang) => string | null];
const PATTERNS: Pattern[] = [
  [/^Sign in as (.+)$/, (m, l) => (l === "te" ? `${m[1]} గా సైన్ ఇన్ చేయండి` : `${m[1]} के रूप में साइन इन करें`)],
  [/^Section (?!Officer)(.+)$/, (m, l) => (l === "te" ? `సెక్షన్ ${m[1]}` : `अनुभाग ${m[1]}`)],
  [/^(Unclassified|Restricted|Confidential|Secret) clearance$/, (m, l) => {
    const w = word(m[1], l);
    return w ? (l === "te" ? `${w} క్లియరెన్స్` : `${w} क्लीयरेंस`) : null;
  }],
  [/^(\d+) officers?$/, (m, l) => `${m[1]} ${l === "te" ? "అధికారులు" : "अधिकारी"}`],
  [/^(\d+) files?$/, (m, l) => `${m[1]} ${l === "te" ? "ఫైళ్లు" : "फ़ाइलें"}`],
  [/^No officer matches “(.*)”\.$/, (m, l) => (l === "te" ? `“${m[1]}” కు ఏ అధికారీ సరిపోలలేదు.` : `“${m[1]}” से कोई अधिकारी मेल नहीं खाता।`)],
  [/^(.+) \(\d+\)$/, (m, l) => word(m[1], l)],
];

/** The text in `lang`, or null when it is not fixed screen text (a name, a note, a number…). */
export function translate(text: string, lang: Lang): string | null {
  if (lang === "en") return null;
  const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(text);
  if (!m || !m[2]) return null;
  const core = m[2];
  let out = word(core, lang);
  if (out === null) {
    for (const [re, fn] of PATTERNS) {
      const r = re.exec(core);
      if (r) { out = fn(r, lang); if (out !== null) break; }
    }
  }
  if (out === null && core.includes(", ")) {
    const parts = core.split(", ").map((s) => word(s, lang));
    if (parts.every((p) => p !== null)) out = parts.join(", ");
  }
  return out === null ? null : m[1] + out + m[3];
}

// ---- the chosen language ----
let current: Lang = "en";
const listeners = new Set<() => void>();
const isLang = (v: unknown): v is Lang => v === "en" || v === "te" || v === "hi";

export function storedLang(): Lang {
  try { const v = typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null; return isLang(v) ? v : "en"; }
  catch { return "en"; }
}
export const getLang = (): Lang => current;
export function setLang(l: Lang): void {
  if (l === current) return;
  current = l;
  try { localStorage.setItem(KEY, l); } catch { /* kept for this visit only */ }
  if (typeof document !== "undefined") document.documentElement.lang = HTML_LANG[l];
  listeners.forEach((f) => f());
}
const subscribe = (f: () => void) => { listeners.add(f); return () => { listeners.delete(f); }; };
export const useLang = (): Lang => useSyncExternalStore(subscribe, getLang, () => "en" as Lang);

// ---- the page translator ----
const ATTRS = ["placeholder", "title", "aria-label", "alt"] as const;
const SKIP = "textarea, script, style, code, pre, [translate=no], [contenteditable=true]";
type Seen = { orig: string; shown: string };
const texts = new WeakMap<Text, Seen>();
const attrs = new WeakMap<Element, Map<string, Seen>>();

function syncText(n: Text): void {
  if (n.parentElement?.closest(SKIP)) return;
  const prev = texts.get(n);
  const cur = n.data;
  const orig = prev && cur === prev.shown ? prev.orig : cur;
  if (!prev && current === "en") return;
  const target = (current === "en" ? null : translate(orig, current)) ?? orig;
  if (target !== cur) n.data = target;
  texts.set(n, { orig, shown: target });
}

function syncAttr(el: Element, name: string): void {
  if (el.closest(SKIP) && el.tagName !== "TEXTAREA") return;
  const cur = el.getAttribute(name);
  if (cur === null) return;
  let m = attrs.get(el);
  const prev = m?.get(name);
  const orig = prev && cur === prev.shown ? prev.orig : cur;
  if (!prev && current === "en") return;
  const target = (current === "en" ? null : translate(orig, current)) ?? orig;
  if (target !== cur) el.setAttribute(name, target);
  if (!m) { m = new Map(); attrs.set(el, m); }
  m.set(name, { orig, shown: target });
}

function walk(root: Node): void {
  if (root.nodeType === 3) { syncText(root as Text); return; }
  if (root.nodeType !== 1) return;
  const el = root as Element;
  const area = el.tagName === "TEXTAREA"; // its placeholder is screen text, its content is not
  if (el.closest(SKIP) && !area) return;
  for (const a of ATTRS) if (el.hasAttribute(a)) syncAttr(el, a);
  if (!area) el.childNodes.forEach(walk);
}

let started = false;
/** Start once, at page load: translates the page, and every change React makes to it after. */
export function startTranslator(): void {
  if (started || typeof document === "undefined") return;
  started = true;
  current = storedLang();
  document.documentElement.lang = HTML_LANG[current];
  const obs = new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === "characterData") syncText(r.target as Text);
      else if (r.type === "attributes") syncAttr(r.target as Element, r.attributeName as string);
      else r.addedNodes.forEach(walk);
    }
  });
  obs.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: [...ATTRS] });
  const all = () => walk(document.body);
  subscribe(all);
  all();
}
