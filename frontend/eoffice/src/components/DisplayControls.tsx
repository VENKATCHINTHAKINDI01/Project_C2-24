import { LANGS, setLang, useLang } from "../i18n";
import type { Preferences } from "../types";

const SIZES: { v: Preferences["text_size"]; label: string; title: string; cls: string }[] = [
  { v: "normal", label: "A", title: "Normal text", cls: "s1" },
  { v: "large", label: "A", title: "Larger text", cls: "s2" },
  { v: "larger", label: "A", title: "Largest text", cls: "s3" },
];

/** Text size and language, top right of every page (ADR-0073). Both are kept in this browser. */
export function DisplayControls({ size, onSize }: { size: Preferences["text_size"]; onSize: (s: Preferences["text_size"]) => void }) {
  const lang = useLang();
  return (
    <div className="display-controls">
      <div className="dc-group" role="group" aria-label="Text size">
        {SIZES.map((s) => (
          <button key={s.v} type="button" className={`dc-size ${s.cls}`} aria-pressed={size === s.v}
            title={s.title} aria-label={s.title} onClick={() => onSize(s.v)}>{s.label}</button>
        ))}
      </div>
      <div className="dc-group" role="group" aria-label="Language">
        {LANGS.map((l) => (
          <button key={l.code} type="button" className="dc-lang" aria-pressed={lang === l.code}
            lang={l.code === "en" ? "en" : l.code} translate="no" title={l.name} onClick={() => setLang(l.code)}>{l.label}</button>
        ))}
      </div>
    </div>
  );
}
