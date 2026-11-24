import { SendHorizontal, Square } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../api";
import type { Api } from "../api";
import type { Confidence, ChatEvent, ChatStatement, ChatTurn } from "../types";
import { usePrefs } from "../prefs";
import { CitePreview } from "./CitePreview";
import { Feedback } from "./Feedback";

/** "Ask C2-24" — the conversation for the open file (plan §8.1, §10.1; ADR-0029). Every statement
 * shows where it comes from; nothing here is inserted into the file except on the officer's click. */
export function ChatPanel({ api, computerNo, onInserted, onOpenDoc, suggestions = [], titled = true }: {
  api: Api; computerNo?: string; onInserted?: () => void;
  onOpenDoc?: (canonicalId: string) => void;
  /** Questions this file invites (ADR-0034): one click asks them. */
  suggestions?: string[];
  /** false inside a panel that has its own heading (Ask AI) */
  titled?: boolean;
}) {
  const [session, setSession] = useState<string | null>(null);
  const [turns, setTurns] = useState<{ asked: string; reply: ChatTurn }[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inserted, setInserted] = useState<string | null>(null);

  const [pending, setPending] = useState<Pending | null>(null);
  const stop = useRef<AbortController | null>(null);
  const input = useRef<HTMLInputElement | null>(null);
  const latest = turns[turns.length - 1]?.reply;

  const prefs = usePrefs();
  // Ctrl/⌘+K: ask; Ctrl/⌘+Enter: insert the latest first-cut note as a Yellow Note (a draft)
  useEffect(() => {
    if (!prefs.shortcuts) return undefined; // switched off in Settings
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      if (e.key.toLowerCase() === "k") {
        e.preventDefault();
        // a box in a collapsed panel cannot take focus: open the panel on Ask (AssistDock)
        if (input.current?.offsetParent) input.current.focus();
        else window.dispatchEvent(new Event("c2:ask"));
      }
      if (e.key === "Enter" && latest?.first_cut?.note?.sections.length && computerNo && !busy) {
        e.preventDefault(); void insert(latest);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  async function send(text?: string) {
    const asked = (text ?? message).trim();
    if (asked.length < 2) return;
    setBusy(true); setError(null);
    setPending({ asked, stage: STAGES.searching, statements: [], review: [] });
    const ctrl = new AbortController();
    stop.current = ctrl;
    const onEvent = (e: ChatEvent) => setPending((p) => (p ? step(p, e) : p));
    try {
      let reply: ChatTurn;
      try {
        if (!prefs.stream_answers) throw new Error("streaming off"); // Settings: whole answer at once
        reply = await api.chatStream(asked, session, computerNo, onEvent, ctrl.signal);
      } catch (e) {
        if (ctrl.signal.aborted) throw e;
        if (e instanceof ApiError) throw e;
        reply = await api.chat(asked, session, computerNo); // streaming not available: one piece
      }
      setSession(reply.session_id);
      setTurns((t) => [...t, { asked, reply }]);
      setMessage("");
      setPending(null);
    } catch (e) {
      if (ctrl.signal.aborted) {
        setPending((p) => (p ? { ...p, stopped: true } : p));
      } else {
        setPending(null);
        setError(e instanceof Error ? e.message : "Request failed");
      }
    } finally { setBusy(false); stop.current = null; }
  }

  async function insert(t: ChatTurn) {
    const cut = t.first_cut;
    if (!cut || !computerNo || !cut.note) return;
    const r = await api.insertYellowNote(computerNo, cut.note_text, cut.citations, cut.request_id);
    setInserted(r.draft_id); onInserted?.();
  }

  return (
    <section className="chat">
      {titled && <h3>Ask C2-24</h3>}
      <p className="caveat">Answers come only from records you may see, each line with its source. Drafts only.</p>
      {turns.map(({ asked, reply }, i) => (
        <ChatReply key={i} api={api} asked={asked} reply={reply} onOpenDoc={onOpenDoc}
          onInsert={computerNo ? () => insert(reply) : undefined} />
      ))}
      {pending && <PendingReply p={pending} />}
      {inserted && <p className="ok">Inserted as Yellow Note (draft {inserted}). It is yours to edit and sign.</p>}
      {suggestions.length > 0 && !busy && (
        <div className="chips" aria-label="Suggested questions">
          {suggestions.map((q) => <button key={q} className="chip" onClick={() => { setMessage(q); void send(q); }}>{q}</button>)}
        </div>
      )}
      <div className="row composer">
        <input ref={input} aria-label="Ask C2-24 (Ctrl+K)" onKeyDown={(e) => { if (e.key === "Enter" && !e.ctrlKey && !e.metaKey && !busy) void send(); }} value={message} onChange={(e) => setMessage(e.target.value)} maxLength={500}
          placeholder='e.g. "Has this been decided before?" then "Draft the noting using that precedent."' />
        {busy
          ? <button onClick={() => stop.current?.abort()}><Square size={14} aria-hidden="true" />Stop</button>
          : <button className="primary" onClick={() => void send()}><SendHorizontal size={14} aria-hidden="true" />Ask</button>}
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

const STAGES = {
  searching: "Searching the records you may see…",
  writing: "Writing the answer…",
  checking: "Checking each statement against its source…",
};

interface Pending {
  asked: string; stage: string; statements: ChatStatement[]; review: ChatStatement[]; stopped?: boolean;
}

function step(p: Pending, e: ChatEvent): Pending {
  switch (e.type) {
    case "stage":
      return {
        ...p,
        stage: e.stage === "found"
          ? `Found ${e.records ?? 0} record(s) you may see${e.rung ? ` (${e.rung})` : ""}…`
          : STAGES[e.stage],
      };
    case "statement": return { ...p, statements: [...p.statements, e.statement] };
    case "review": return { ...p, review: [...p.review, e.statement] };
    default: return p;
  }
}

/** The answer as it is written (ADR-0033). Only statements that already passed the citation check
 *  arrive here; the full answer replaces this when it is done. */
function PendingReply({ p }: { p: Pending }) {
  return (
    <div className="turn pending" aria-live="polite" aria-busy={!p.stopped}>
      <p className="asked"><strong>You:</strong> {p.asked}</p>
      {p.stopped
        ? <p className="meta">Stopped. The statements shown were checked; the answer may be incomplete.</p>
        : <p className="stage"><span className="dot" />{p.stage}</p>}
      {p.statements.length > 0 && (
        <ol>{p.statements.map((s, i) => <StatementLine key={i} s={s} typing={!p.stopped} />)}</ol>
      )}
      {p.review.length > 0 && (
        <div className="review"><h4>Review needed</h4>
          <ol>{p.review.map((s, i) => <StatementLine key={i} s={s} typing={!p.stopped} />)}</ol>
        </div>
      )}
    </div>
  );
}

/** Reveals already-checked text at reading pace; the whole text is in the DOM for screen readers. */
function Typed({ text, on }: { text: string; on: boolean }) {
  const [n, setN] = useState(on ? 0 : text.length);
  useEffect(() => {
    if (!on || n >= text.length) return;
    const t = setTimeout(() => setN((k) => Math.min(text.length, k + 4)), 16);
    return () => clearTimeout(t);
  }, [n, on, text.length]);
  return (
    <>
      <span aria-hidden={n < text.length}>{text.slice(0, n)}</span>
      {n < text.length && <span className="sr-only">{text}</span>}
    </>
  );
}

const THUMBS: [("thumbs_up" | "thumbs_down"), string][] = [["thumbs_up", "👍"], ["thumbs_down", "👎"]];

export function ChatReply({ api, asked, reply, onOpenDoc, onInsert }: {
  api?: Api; asked: string; reply: ChatTurn; onOpenDoc?: (cid: string) => void; onInsert?: () => void;
}) {
  const cut = reply.first_cut;
  return (
    <div className="turn">
      <p className="asked"><strong>You:</strong> {asked}</p>
      {reply.used_earlier_turn && <p className="meta">Using what this conversation found earlier (re-checked now).</p>}
      {reply.from_cache && <p className="meta">Same answer as before for your access.</p>}
      {reply.notices.map((n, i) => <p key={i} className="caveat">{n}</p>)}
      {reply.statements.length > 0 ? (
        <ol>{reply.statements.map((s, i) => (
          <StatementLine key={i} s={s} api={api} onOpenDoc={onOpenDoc}
            feedback={api && s.citations[0] ? <Feedback api={api} choices={THUMBS}
              target={{ kind: "statement", request_id: reply.request_id, canonical_id: s.citations[0].canonical_id }} /> : null} />
        ))}</ol>
      ) : (
        <p className="noanswer">{reply.message ?? "No sufficiently supported answer was found in the authorised records."}</p>
      )}
      {reply.statements.length === 0 && reply.documents.length > 0 && (
        // no answer written (no model, or nothing supported): the records found, to open and read
        <ul className="found-docs" aria-label="Records found">
          {reply.documents.map((d) => (
            <li key={d}>{onOpenDoc ? <button className="link" onClick={() => onOpenDoc(d)}>{d}</button> : d}</li>
          ))}
        </ul>
      )}
      {reply.review_needed.length > 0 && (
        <div className="review">
          <h4>Review needed</h4>
          <ol>{reply.review_needed.map((s, i) => <StatementLine key={i} s={s} onOpenDoc={onOpenDoc} />)}</ol>
        </div>
      )}
      {reply.removed > 0 && <p className="meta">{reply.removed} statement(s) withheld: not supported by the cited text.</p>}
      {api && reply.status !== "denied" && reply.status !== "not_run" && (
        <p className="meta">Was this answer useful?{" "}
          <Feedback api={api} choices={THUMBS}
            target={{ kind: "answer", request_id: reply.request_id, session_id: reply.session_id }} />
        </p>
      )}
      {cut && (
        <div className="firstcut">
          <h4>First-cut note for this file</h4>
          <pre>{cut.note?.sections.length ? cut.note_text : cut.body}</pre>
          {cut.note && cut.note.removed > 0 && <p className="meta">{cut.note.removed} line(s) removed by the check.</p>}
          {onInsert && cut.note?.sections.length ? <button onClick={onInsert}>Insert as Yellow Note</button> : null}
        </div>
      )}
    </div>
  );
}

/** The statement as it would go into a note: its words, then the orders in e-Office reference form. */
export function withReferences(s: ChatStatement): string {
  const refs = [...new Set(s.citations.map((c) => c.reference || c.canonical_id))];
  return refs.length ? `${s.text} (${refs.join("; ")})` : s.text;
}

function CopyRef({ s }: { s: ChatStatement }) {
  const [done, setDone] = useState(false);
  return (
    <button className="fb" title="Copy with its reference, for pasting into a note"
      onClick={() => { void navigator.clipboard?.writeText(withReferences(s)).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }); }}>
      {done ? "Copied" : "Copy"}
    </button>
  );
}

const BAND: Record<Confidence["band"], string> = {
  high: "High confidence", medium: "Medium confidence", low: "Low confidence: check before relying on it",
};

/** How far this statement can be relied on (ADR-0054): the band, and on opening, the reasons —
 *  facts the system holds, weakest first. Never the model's own opinion of itself. */
function ConfidenceNote({ c }: { c: Confidence }) {
  const why = [...c.factors].sort((a, b) => a.value - b.value);
  return (
    <details className={`conf conf-${c.band}`}>
      <summary>{BAND[c.band]}</summary>
      <ul>{why.map((f) => <li key={f.name}>{f.reason}</li>)}</ul>
    </details>
  );
}

function StatementLine({ s, api, onOpenDoc, feedback, typing = false }: {
  s: ChatStatement; api?: Api; onOpenDoc?: (cid: string) => void; feedback?: ReactNode; typing?: boolean;
}) {
  return (
    <li>
      {typing ? <Typed text={s.text} on /> : s.text}
      {s.quote && <q className="quote">{s.quote}</q>}
      <span className="sources">
        {s.source === "order records" ? "From the order records: "
          : s.source === "file records" ? "Counted from the file records you may see: "
          : s.source === "link records" ? "From the links between records: "
          : s.source === "entity records" ? "From the records that name them: " : "Source: "}
        {s.citations.map((c, i) => (
          <CitePreview key={i} api={api} c={c} quote={s.quote}>
            <button className="cite" onClick={() => onOpenDoc?.(c.canonical_id)}>
              {c.reference || c.canonical_id}{c.status ? ` (${c.status})` : ""}
            </button>
          </CitePreview>
        ))}
      </span>
      {!typing && s.confidence && <ConfidenceNote c={s.confidence} />}
      {!typing && <CopyRef s={s} />}
      {feedback}
    </li>
  );
}
