import { useCallback, useEffect, useRef, useState } from "react";
import type { Api } from "../api";
import type { NoteSuggestion, PolishMode, PolishResult } from "../types";

/** ADR-0072: Gmail-style help in the note editor. Suggested notes come from the file's notes
 *  (mainly the last direction); Polish rewrites the officer's own text. Nothing is saved here:
 *  the text goes into the editor, the officer edits it and saves the note themselves. */

export const MIN_POLISH_WORDS = 12;

const MODES: { mode: PolishMode; label: string }[] = [
  { mode: "polish", label: "Polish" },
  { mode: "formal", label: "More formal" },
  { mode: "short", label: "Shorten" },
  { mode: "elaborate", label: "Add facts from the file" },
];

export const wordCount = (t: string) => (t.trim().match(/\S+/g) ?? []).length;

type Piece = { kind: "same" | "del" | "ins"; text: string };

/** Word-level difference between the officer's text and the polished one (longest common run). */
export function wordDiff(a: string, b: string): Piece[] {
  const A = a.split(/(\s+)/), B = b.split(/(\s+)/);
  if (A.length * B.length > 250_000) return [{ kind: "del", text: a }, { kind: "ins", text: b }];
  const n = A.length, m = B.length;
  const L = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: Piece[] = [];
  const push = (kind: Piece["kind"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.text += text; else out.push({ kind, text });
  };
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { push("same", A[i]); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) { if (A[i].trim()) push("del", A[i] + " "); i++; }
    else { push(B[j].trim() ? "ins" : "same", B[j]); j++; }
  }
  for (; i < n; i++) if (A[i].trim()) push("del", A[i] + " ");
  for (; j < m; j++) push(B[j].trim() ? "ins" : "same", B[j]);
  return out;
}

const FALLBACK_TEXT: Record<string, string> = {
  "model not configured": "AI is not available here, so only a basic clean-up is shown (abbreviations expanded, sentences completed).",
  "model unavailable": "AI is not available just now, so only a basic clean-up is shown.",
  "daily limit reached": "Today's AI wording requests are used up, so only a basic clean-up is shown.",
  "usage count unavailable": "AI is not available just now, so only a basic clean-up is shown.",
  "changed what the note says": "The AI version changed or added a name, date or figure, so it was withheld. Only a basic clean-up is shown.",
  "model returned nothing": "The AI returned nothing, so only a basic clean-up is shown.",
};

export function SuggestedNotes({ api, computerNo, active, onPick }: {
  api: Api; computerNo: string; active: boolean; onPick: (text: string) => void;
}) {
  const [items, setItems] = useState<NoteSuggestion[] | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [preview, setPreview] = useState<NoteSuggestion | null>(null);
  const [done, setDone] = useState(false);
  const asked = useRef(false);
  useEffect(() => {
    if (!active || asked.current) return;
    asked.current = true;
    // streamed: each suggestion appears as soon as it passed its check; `done` replaces them
    api.noteSuggestionsStream(computerNo, (e) => {
      if (e.type === "suggestion") setItems((cur) => [...(cur ?? []), e.suggestion]);
    })
      .then((r) => { setItems(r.suggestions); setReason(r.reason); setDone(true); })
      .catch(() => { setItems((cur) => cur ?? []); setDone(true); });
  }, [active, api, computerNo]);
  if (!active) return null;
  if (items === null || (items.length === 0 && !done)) return <p className="muted small note-sugs-wait">Looking at the notes on this file for suggestions…</p>;
  if (items.length === 0) return null;
  return (
    <div className="note-sugs">
      <p className="muted small">Suggested notes, from {items[0].sources.map((n) => `N${n}`).join(", ")}{reason ? " (AI not available: a simple acknowledgement)" : ""}</p>
      <div className="note-sug-row" role="group" aria-label="Suggested notes">
        {items.map((s) => (
          <button key={s.label} type="button" className="note-sug"
            onMouseEnter={() => setPreview(s)} onFocus={() => setPreview(s)} onMouseLeave={() => setPreview(null)}
            onClick={() => { onPick(s.text); setPreview(null); }}>{s.label}</button>
        ))}
      </div>
      {preview && <blockquote className="note-sug-preview" aria-live="polite">{preview.text}<span className="muted small"> — from {preview.sources.map((n) => `N${n}`).join(", ")}</span></blockquote>}
    </div>
  );
}

export function PolishPanel({ api, computerNo, original, onUse, onClose }: {
  api: Api; computerNo: string; original: string; onUse: (text: string) => void; onClose: () => void;
}) {
  const [mode, setMode] = useState<PolishMode>("polish");
  const [instruction, setInstruction] = useState("");
  const [res, setRes] = useState<PolishResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(""); // the checked sentences so far, while it is written
  const run = useCallback((m: PolishMode, ins = "") => {
    setMode(m); setBusy(true); setError(null); setRes(null); setLive("");
    api.polishNoteStream(computerNo, original, m, ins, (e) => {
      if (e.type === "sentence") setLive((cur) => cur + (e.new_paragraph ? "\n" : cur ? " " : "") + e.text);
    })
      .then(setRes).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  }, [api, computerNo, original]);
  useEffect(() => { run("polish"); }, [run]);
  const added = new Map((res?.added ?? []).map((a) => [a.sentence, a.note_no]));
  return (
    <section className="polish-panel" aria-label="Polished version">
      <div className="polish-head">
        <strong>Polished version</strong>
        <div className="polish-modes" role="group" aria-label="Style">
          {MODES.map((m) => (
            <button key={m.mode} type="button" className="chip" aria-pressed={mode === m.mode && !instruction}
              disabled={busy} onClick={() => { setInstruction(""); run(m.mode); }}>{m.label}</button>
          ))}
        </div>
      </div>
      {busy && (
        <div className="polish-live" aria-live="polite">
          {live ? <>{live}<span className="polish-caret" aria-hidden="true" /></> : <span className="muted small">Rewriting your note…</span>}
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {res && !busy && (
        <>
          <div className="polish-diff">
            {wordDiff(original, res.text).map((p, k) =>
              p.kind === "same" ? <span key={k}>{p.text}</span>
                : p.kind === "del" ? <del key={k}>{p.text}</del> : <ins key={k}>{p.text}</ins>)}
          </div>
          <ul className="polish-checks small">
            {res.reason && res.text.trim() === original.trim()
              ? <li className="warn-text">No changes to suggest. {FALLBACK_TEXT[res.reason] ?? res.reason}</li>
              : res.reason
              ? <li className="warn-text">{FALLBACK_TEXT[res.reason] ?? res.reason}{res.withheld.length > 0 && ` (${res.withheld.join(", ")})`}</li>
              : <li className="ok-text">✓ {res.kept.length ? `All ${res.kept.length} dates, numbers and references kept unchanged` : "Nothing in your note changed meaning"}</li>}
            {added.size > 0 && [...added].map(([s, n]) => <li key={s} className="ok-text">✓ Added from N{n}: “{s}”</li>)}
            {!res.reason && added.size === 0 && <li className="ok-text">✓ No new facts added</li>}
          </ul>
          <form className="polish-custom" onSubmit={(e) => { e.preventDefault(); if (instruction.trim()) run(mode, instruction.trim()); }}>
            <input id="polish-instruction" aria-label="Say how to change it" maxLength={200} value={instruction}
              onChange={(e) => setInstruction(e.target.value)} placeholder="Or say how to change it, e.g. mention the vacancy letter" />
            <button type="submit" disabled={busy || !instruction.trim()}>Apply</button>
          </form>
        </>
      )}
      <div className="actions">
        <button type="button" onClick={onClose}>Keep my text</button>
        <button type="button" className="primary" disabled={!res || busy} onClick={() => res && onUse(res.text)}>Use this version</button>
      </div>
    </section>
  );
}
