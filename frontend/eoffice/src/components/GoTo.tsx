import { Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { FileRow } from "../types";

/** Best matches for what was typed: exact Computer No. or File No. first, then the start of
 *  either, then any part of the File No. or subject. Only from the files the officer can open
 *  (the list the server gave them), so this never reveals a file they could not open anyway. */
export function matchFiles(files: FileRow[], typed: string, limit = 8): FileRow[] {
  const q = typed.trim().toLowerCase();
  if (!q) return [];
  const rank = (f: FileRow): number => {
    const no = f.file_no.toLowerCase(), cno = f.computer_no.toLowerCase(), subj = f.subject.toLowerCase();
    if (cno === q || no === q) return 0;
    if (cno.startsWith(q) || no.startsWith(q)) return 1;
    if (no.includes(q)) return 2;
    return q.split(/\s+/).every((w) => subj.includes(w) || no.includes(w)) ? 3 : 9;
  };
  return files.map((f) => [rank(f), f] as const).filter(([r]) => r < 9)
    .sort((a, b) => a[0] - b[0] || a[1].file_no.localeCompare(b[1].file_no)).slice(0, limit).map(([, f]) => f);
}

/** "Go to file" in the top bar. `/` focuses it from anywhere (not while typing elsewhere). */
export function GoTo({ files, open }: { files: FileRow[]; open: (computerNo: string) => void }) {
  const [typed, setTyped] = useState("");
  const [at, setAt] = useState(0);
  const [shown, setShown] = useState(false);
  const box = useRef<HTMLInputElement | null>(null);
  const hits = useMemo(() => matchFiles(files, typed), [files, typed]);
  useEffect(() => setAt(0), [typed]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
      e.preventDefault(); box.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const go = (f: FileRow | undefined) => {
    if (!f) return;
    open(f.computer_no); setTyped(""); setShown(false); box.current?.blur();
  };
  return (
    <div className="goto" role="search">
      <Search className="goto-icon" size={16} aria-hidden="true" />
      <kbd className="goto-key" aria-hidden="true">/</kbd>
      <input ref={box} value={typed} placeholder="Go to file — File No., Comp. No. or subject"
        aria-label="Go to file" aria-expanded={shown && hits.length > 0} aria-controls="goto-list" aria-autocomplete="list"
        aria-activedescendant={shown && hits[at] ? `goto-${hits[at].computer_no}` : undefined} role="combobox"
        onChange={(e) => { setTyped(e.target.value); setShown(true); }}
        onFocus={() => setShown(true)} onBlur={() => setTimeout(() => setShown(false), 120)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setAt((i) => Math.min(hits.length - 1, i + 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setAt((i) => Math.max(0, i - 1)); }
          else if (e.key === "Enter") { e.preventDefault(); go(hits[at]); }
          else if (e.key === "Escape") { setTyped(""); box.current?.blur(); }
        }} />
      {shown && typed.trim() && (
        <ul id="goto-list" className="goto-list" role="listbox">
          {hits.map((f, i) => (
            <li key={f.computer_no} id={`goto-${f.computer_no}`} role="option" aria-selected={i === at}
              className={i === at ? "on" : undefined} onMouseDown={(e) => { e.preventDefault(); go(f); }} onMouseEnter={() => setAt(i)}>
              <span className="fileno">{f.file_no}</span>
              <span className="goto-subject">{f.subject}</span>
            </li>
          ))}
          {hits.length === 0 && <li className="muted goto-none">No file you can open matches “{typed.trim()}”.</li>}
        </ul>
      )}
    </div>
  );
}
