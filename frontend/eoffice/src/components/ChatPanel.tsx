import { History, Plus, SendHorizontal, Square, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../api";
import type { Api } from "../api";
import type { ChatCitation, ChatConversationRow, Confidence, ChatEvent, ChatStatement, ChatTurn } from "../types";
import { usePrefs } from "../prefs";
import { CitePreview } from "./CitePreview";
import { Feedback } from "./Feedback";

/** A question about the open file that one of its own tools answers (summary, movements, records,
 *  pre-send check, drafts…): read through the file's own scoped endpoint, no search and no model. */
export interface FileTool {
  id: string;
  /** shown as a chip when set */
  label?: string;
  /** a typed question this tool answers (the fixed rules: the fallback when the model cannot say) */
  match: (q: string) => boolean;
  /** whether the tool can answer this message at all (e.g. the general chat needs a named file) */
  ready?: (q: string) => boolean;
  run: (asked: string) => Promise<ReactNode>;
}

/** One exchange on screen: a searched answer, a tool's card, or a restored turn (ADR-0066). */
interface Shown { asked: string; reply?: ChatTurn; card?: ReactNode; tool?: string; withheld?: boolean; auto?: boolean }

/** What the file chat asks by itself when it opens (25 Nov 2026): the whole file, end to end. */
export const AUTO_SUMMARY_ASK =
  "Summarise this file end to end: what it is about, what was proposed and by whom, what was decided or " +
  "directed and by whom, where the file is now and what is pending.";

const fmtWhen = (iso: string) => new Date(iso).toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

/** "Ask C2-24" — a conversation (plan §8.1, §10.1; ADR-0029). Every statement shows where it comes
 * from; nothing is inserted into the file except on the officer's click. The server keeps the
 * officer's conversations (ADR-0066): the last one here opens again and continues where it
 * stopped; earlier ones can be reopened or deleted. */
export function ChatPanel({ api, computerNo, onInserted, onOpenDoc, suggestions = [], titled = true, tools = [], caveat, autoSummary = false }: {
  api: Api; computerNo?: string; onInserted?: () => void;
  onOpenDoc?: (canonicalId: string) => void;
  /** Questions this file invites (ADR-0034): one click asks them. */
  suggestions?: string[];
  /** false inside a panel that has its own heading (Ask AI) */
  titled?: boolean;
  /** the open file's own answers (ADR-0064 addendum 1); asked by chip or by a matching question */
  tools?: FileTool[];
  caveat?: string;
  /** the file chat: when its panel opens, start with the file's summary instead of suggestions */
  autoSummary?: boolean;
}) {
  const place = computerNo ?? "all";
  const [session, setSession] = useState<string | null>(null);
  const [turns, setTurns] = useState<Shown[]>([]);
  const [convs, setConvs] = useState<ChatConversationRow[]>([]);
  const [listing, setListing] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inserted, setInserted] = useState<string | null>(null);

  const [pending, setPending] = useState<Pending | null>(null);
  const stop = useRef<AbortController | null>(null);
  const input = useRef<HTMLInputElement | null>(null);
  const latest = [...turns].reverse().find((x) => x.reply)?.reply;
  // the newest exchange scrolls into view from its question (a long draft is read from the top)
  const end = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const all = end.current?.parentElement?.querySelectorAll<HTMLElement>(".turn");
    all?.[all.length - 1]?.scrollIntoView?.({ block: "start" });
  }, [turns.length, pending?.asked]);

  // the officer's conversations here; the latest one opens again (ADR-0066)
  const refresh = () => api.chatHistory?.(place).then((r) => setConvs(r.conversations)).catch(() => undefined);
  const open = async (id: string) => {
    setError(null); setListing(false);
    try {
      const c = await api.chatConversation(id);
      setSession(c.conversation_id); setInserted(null);
      const shown = c.turns.map((x): Shown => (x.kind === "tool"
        ? { asked: x.asked, tool: x.tool ?? undefined, auto: x.asked === AUTO_SUMMARY_ASK }
        : x.answer ? { asked: x.asked, reply: x.answer } : { asked: x.asked, withheld: true }));
      setTurns(shown);
      // a file tool's answer is never stored: read the latest ones again now, under today's access
      const recent = shown.map((x, i) => [x, i] as const).filter(([x]) => x.tool).slice(-5);
      for (const [x, i] of recent) {
        const tool = tools.find((t) => t.id === x.tool);
        if (!tool) continue;
        void tool.run(x.asked).then((card) => setTurns((t) => t.map((y, j) => (j === i && y.asked === x.asked ? { ...y, card } : y))))
          .catch(() => undefined);
      }
    } catch { setConvs((cs) => cs.filter((c) => c.conversation_id !== id)); }
  };
  // a tool asked from the page (Send, First-cut note) before the history is back waits for it, so
  // it lands in the conversation it continues
  const [loaded, setLoaded] = useState(false);
  const queued = useRef<string | null>(null);
  useEffect(() => {
    let gone = false;
    const done = () => { if (!gone) setLoaded(true); };
    if (!api.chatHistory) { done(); return undefined; }
    api.chatHistory(place).then(async (r) => {
      if (gone) return;
      setConvs(r.conversations);
      // like a chat app: the conversation continues if it was used in the last two hours; an older
      // one waits under "Earlier chats" and the officer starts fresh
      const last = r.conversations[0];
      // the file chat starts with a fresh summary instead; its earlier chats stay listed
      if (!autoSummary && last && Date.now() - new Date(last.updated_at).getTime() < 2 * 3600_000) await open(last.conversation_id);
    }).catch(() => undefined).finally(done);
    return () => { gone = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per place
  }, [api, place]);
  const newChat = () => { setSession(null); setTurns([]); setInserted(null); setError(null); setListing(false); input.current?.focus(); };
  const remove = (id: string) => {
    void api.deleteChat(id).then(() => {
      setConvs((cs) => cs.filter((c) => c.conversation_id !== id));
      if (id === session) newChat();
    }).catch((e: Error) => setError(e.message));
  };

  const prefs = usePrefs();
  // Ctrl/⌘+K: ask; Ctrl/⌘+Enter: insert the latest first-cut note as a Yellow Note (a draft)
  useEffect(() => {
    if (!prefs.shortcuts) return undefined; // switched off in Settings
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      if (e.key.toLowerCase() === "k") {
        e.preventDefault();
        // a box in a closed panel cannot take focus: open the panel on Ask (AssistDock)
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

  // the file page's own buttons (Send = pre-send check, First-cut note) ask through this chat
  useEffect(() => {
    const onTool = (e: Event) => {
      const id = (e as CustomEvent<string>).detail;
      if (!loaded) { queued.current = id; return; }
      const tool = tools.find((x) => x.id === id);
      if (tool && !busy) void runTool(tool, tool.label ?? tool.id);
    };
    window.addEventListener("c2:file-tool", onTool);
    return () => window.removeEventListener("c2:file-tool", onTool);
  });

  // the file chat's summary: once per opening of the file, when its panel is first shown
  const summarised = useRef(false);
  const summarise = () => {
    const tool = tools.find((x) => x.id === "summary");
    if (!autoSummary || summarised.current || !loaded || busy || !tool) return;
    if (!input.current?.offsetParent) return; // the panel is closed: wait until it opens
    summarised.current = true;
    void runTool(tool, AUTO_SUMMARY_ASK, true);
  };
  useEffect(() => {
    window.addEventListener("c2:file-panel-open", summarise);
    return () => window.removeEventListener("c2:file-panel-open", summarise);
  });
  useEffect(() => {
    if (!loaded || !queued.current) { summarise(); return; }
    const tool = tools.find((x) => x.id === queued.current);
    queued.current = null;
    if (tool) void runTool(tool, tool.label ?? tool.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once the history is back
  }, [loaded]);

  /** What the officer is asking for (ADR-0067): the model reads the message and picks one of the
   *  tools offered here, or the search; when it cannot say (no model, error, slow), the fixed
   *  rules decide. Either way the tool is the same scoped endpoint as its button. */
  async function pick(asked: string): Promise<FileTool | null> {
    const offered = tools.filter((x) => x.ready?.(asked) ?? true);
    if (offered.length === 0) return null;
    const base = (id: string) => id.split("@")[0];
    setBusy(true);
    setPending({ asked, stage: "Understanding your question…", statements: [], review: [] });
    try {
      const r = await Promise.race([
        api.intent(asked, computerNo, [...new Set(offered.map((x) => base(x.id)))]),
        new Promise<null>((ok) => setTimeout(() => ok(null), 6000)),
      ]);
      if (r && r.tool) return r.tool === "search" ? null : offered.find((x) => base(x.id) === r.tool) ?? null;
    } catch { /* the rules decide */ } finally { setBusy(false); setPending(null); }
    return offered.find((x) => x.match(asked)) ?? null;
  }

  async function runTool(tool: FileTool, asked: string, auto = false) {
    setBusy(true); setError(null);
    setPending({ asked, auto, stage: auto ? "Reading this file and writing its summary…" : "Reading this file's records…", statements: [], review: [] });
    try {
      const card = await tool.run(asked);
      setTurns((t) => [...t, { asked, card, tool: tool.id, auto }]);
      setMessage("");
      if (computerNo) {
        // kept in the history as the question and the tool only; read again when shown
        void api.chatToolTurn(session, computerNo, asked, tool.id)
          .then((r) => { setSession(r.conversation_id); void refresh(); }).catch(() => undefined);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally { setPending(null); setBusy(false); }
  }

  /** a restored tool turn: read again under the officer's access now */
  async function again(i: number) {
    const tool = tools.find((x) => x.id === turns[i]?.tool);
    if (!tool) return;
    try {
      const card = await tool.run(turns[i].asked);
      setTurns((t) => t.map((x, j) => (j === i ? { ...x, card } : x)));
    } catch (e) { setError(e instanceof Error ? e.message : "Request failed"); }
  }

  async function send(text?: string) {
    const asked = (text ?? message).trim();
    if (asked.length < 2) return;
    const tool = await pick(asked);
    if (tool) { await runTool(tool, asked); return; }
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
      void refresh();
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
      <div className="chat-bar">
        <button className="link" onClick={newChat} disabled={busy || (!session && turns.length === 0)}><Plus size={14} aria-hidden="true" />New chat</button>
        {convs.length > 0 && (
          <button className="link" aria-expanded={listing} onClick={() => setListing((l) => !l)}>
            <History size={14} aria-hidden="true" />Earlier chats ({convs.length})
          </button>
        )}
      </div>
      {listing && (
        <ul className="chat-list" aria-label="Earlier chats">
          {convs.map((c) => (
            <li key={c.conversation_id} className={c.conversation_id === session ? "on" : undefined}>
              <button className="chat-open" onClick={() => void open(c.conversation_id)}>
                <span className="chat-title">{c.title}</span><span className="muted small">{fmtWhen(c.updated_at)}</span>
              </button>
              <button className="icon-btn" aria-label={`Delete chat: ${c.title}`} title="Delete this chat" onClick={() => remove(c.conversation_id)}>
                <Trash2 size={14} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="caveat">{caveat ?? "Answers come only from records you may see, each line with its source. Drafts only."}</p>
      {turns.map((x, i) => (x.reply
        ? <ChatReply key={i} api={api} asked={x.asked} reply={x.reply} onOpenDoc={onOpenDoc}
            onInsert={computerNo ? () => insert(x.reply as ChatTurn) : undefined} />
        : (
          <div key={i} className="turn">
            {!x.auto && <p className="asked"><strong>You:</strong> {x.asked}</p>}
            {x.card ?? (x.withheld
              ? <p className="noanswer">This answer cited records that are no longer available to you, so it is not shown.</p>
              : <button className="link" onClick={() => void again(i)}>Show the current answer</button>)}
          </div>
        )
      ))}
      {pending && <PendingReply p={pending} />}
      <div ref={end} />
      {inserted && <p className="ok">Inserted as Yellow Note (draft {inserted}). It is yours to edit and sign.</p>}
      {suggestions.length > 0 && !computerNo && !busy && turns.length === 0 && (
        <div className="chips" aria-label="Suggested questions">
          {suggestions.map((q) => <button key={q} className="chip" onClick={() => { setMessage(q); void send(q); }}>{q}</button>)}
        </div>
      )}
      <div className="row composer">
        <input ref={input} aria-label="Ask C2-24 (Ctrl+K)" onKeyDown={(e) => { if (e.key === "Enter" && !e.ctrlKey && !e.metaKey && !busy) void send(); }} value={message} onChange={(e) => setMessage(e.target.value)} maxLength={500}
          placeholder={computerNo ? 'Ask about this file, e.g. "Where is this file pending?"' : 'e.g. "Has this been decided before?" then "Draft the noting using that precedent."'} />
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
  /** asked by the chat itself (the file summary on opening): no "You:" line */
  auto?: boolean;
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
  const nums = sourceNumbers([...p.statements, ...p.review]);
  return (
    <div className="turn pending" aria-live="polite" aria-busy={!p.stopped}>
      {!p.auto && <p className="asked"><strong>You:</strong> {p.asked}</p>}
      <div className="reply">
        {p.stopped
          ? <p className="meta">Stopped. The statements shown were checked; the answer may be incomplete.</p>
          : <p className="stage"><span className="dot" />{p.stage}</p>}
        {p.statements.length > 0 && <AnswerBody statements={p.statements} nums={nums} typing={!p.stopped} />}
        {p.review.length > 0 && (
          <div className="review"><h4>Review needed</h4><AnswerBody statements={p.review} nums={nums} typing={!p.stopped} /></div>
        )}
      </div>
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
  const all = [...reply.statements, ...reply.review_needed];
  const nums = sourceNumbers(all);
  return (
    <div className="turn">
      <p className="asked"><strong>You:</strong> {asked}</p>
      <div className="reply">
        {reply.used_earlier_turn && <p className="meta">Using what this conversation found earlier (re-checked now).</p>}
        {reply.from_cache && <p className="meta">Same answer as before for your access.</p>}
        {reply.notices.map((n, i) => <p key={i} className="caveat">{n}</p>)}
        {reply.statements.length > 0 ? (
          reply.composed
            ? <ComposedBody c={reply.composed} statements={reply.statements} nums={nums} onOpenDoc={onOpenDoc} />
            : <AnswerBody statements={reply.statements} nums={nums} onOpenDoc={onOpenDoc} />
        ) : reply.status === "chat" ? (
          <p className="chat-reply">{reply.message}</p>
        ) : (
          <>
            <p className="noanswer">{reply.message ?? "No sufficiently supported answer was found in the authorised records."}</p>
            {reply.status === "no_answer" && (
              <p className="muted small">
                {reply.documents.length > 0
                  ? "These records came closest. Open one to read it, or ask again naming the order number, subject or file."
                  : "Try naming the order number (for example G.O.Ms.No.31 of 2025), the subject or the file number."}
              </p>
            )}
          </>
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
            <AnswerBody statements={reply.review_needed} nums={nums} onOpenDoc={onOpenDoc} />
          </div>
        )}
        {reply.removed > 0 && <p className="meta">{reply.removed} statement(s) withheld: not supported by the cited text.</p>}
        {(reply.conflicts?.length ?? 0) > 0 && (
          <div className="answer-conflicts" role="note">
            <h4>Potential conflict{(reply.conflicts?.length ?? 0) > 1 ? "s" : ""} between the records used</h4>
            <ul>{reply.conflicts?.map((f, i) => (
              <li key={i}><b>{f.type === "G" ? "Hierarchy (G)" : f.type === "B" ? "Same level (B)" : f.type}</b> {f.explanation}{" "}
                {f.evidence_ids.map((e) => <button key={e} className="link" onClick={() => onOpenDoc?.(e.split("#")[0])}>{e.split("#")[0]}</button>)}
              </li>
            ))}</ul>
            <p className="meta">Advisory: the records disagree on this point. Review which one applies; nothing has been decided for you.</p>
          </div>
        )}
        {reply.conflict_check === "incomplete" && <p className="meta">The conflict check between these records did not finish; review before relying on them together.</p>}
        {all.length > 0 && <SourceList statements={all} nums={nums} api={api} requestId={reply.request_id} onOpenDoc={onOpenDoc} />}
        {(all.length > 0 || (api && reply.status !== "denied" && reply.status !== "not_run")) && (
          <div className="reply-actions">
            {all.length > 0 && <CopyText text={reply.statements.map(withReferences).join("\n")} label="Copy answer" />}
            {api && reply.status !== "denied" && reply.status !== "not_run" && (
              <span className="meta">Was this answer useful?{" "}
                <Feedback api={api} choices={THUMBS}
                  target={{ kind: "answer", request_id: reply.request_id, session_id: reply.session_id }} />
              </span>
            )}
          </div>
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
    </div>
  );
}

/** Each record cited in an answer gets one number, in the order the answer first cites it. */
function sourceNumbers(statements: ChatStatement[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const s of statements) for (const c of s.citations) if (!m.has(c.canonical_id)) m.set(c.canonical_id, m.size + 1);
  return m;
}

/** The answer as an assistant writes it (24 Nov 2026): one or two statements as a paragraph, more as
 *  points; each sentence carries small numbered markers to its sources (opened on a click), and a
 *  low-confidence sentence says so where it stands. Every sentence is still one checked statement. */
function AnswerBody({ statements, nums, onOpenDoc, typing = false, points = false }: {
  statements: ChatStatement[]; nums: Map<string, number>; onOpenDoc?: (cid: string) => void; typing?: boolean;
  /** always as points (a composed section) */
  points?: boolean;
}) {
  const sentence = (s: ChatStatement, i: number) => (
    <span key={i} className="sentence">
      {typing ? <Typed text={s.text} on /> : s.text}
      {[...new Set(s.citations.map((c) => c.canonical_id))].map((cid) => (
        <sup key={cid}>
          <button className="cn" title={`Source ${nums.get(cid)}: ${s.citations.find((c) => c.canonical_id === cid)?.reference || cid}`}
            onClick={() => onOpenDoc?.(cid)}>{nums.get(cid)}</button>
        </sup>
      ))}
      {s.confidence?.band === "low" && <span className="lowconf" title={BAND.low}> (check before relying on it)</span>}
      {" "}
    </span>
  );
  return statements.length <= 2 && !points
    ? <p className="answer-text">{statements.map(sentence)}</p>
    : <ul className="answer-points">{statements.map((s, i) => <li key={i}>{sentence(s, i)}</li>)}</ul>;
}

/** ADR-0067: the model's layout of the CHECKED statements — a direct first line (its numbers and
 *  references already checked against the statements it names, server side) and grouped points.
 *  Every statement is still shown once, with its own sources. */
function ComposedBody({ c, statements, nums, onOpenDoc }: {
  c: NonNullable<ChatTurn["composed"]>; statements: ChatStatement[]; nums: Map<string, number>; onOpenDoc?: (cid: string) => void;
}) {
  const at = (i: number) => statements[i - 1];
  const leadCites = [...new Set(c.lead_uses.flatMap((i) => at(i)?.citations.map((x) => x.canonical_id) ?? []))];
  return (
    <>
      {c.lead && (
        <p className="answer-lead">{c.lead}
          {leadCites.map((cid) => <sup key={cid}><button className="cn" onClick={() => onOpenDoc?.(cid)} title={`Source ${nums.get(cid)}`}>{nums.get(cid)}</button></sup>)}
        </p>
      )}
      {c.sections.map((s, k) => {
        const items = s.items.map(at).filter(Boolean) as ChatStatement[];
        return (
          <div key={k} className="answer-section">
            {s.heading && <h4>{s.heading}</h4>}
            <AnswerBody statements={items} nums={nums} onOpenDoc={onOpenDoc} points />
          </div>
        );
      })}
    </>
  );
}

const KIND: Record<ChatStatement["source"], string> = {
  "order records": "From the order records", "file records": "Counted from the file records you may see",
  "link records": "From the links between records", "entity records": "From the records that name them", evidence: "Source",
};

/** The numbered sources under an answer, folded: each record once, with the words it was quoted
 *  for, how far it can be relied on (ADR-0054), a copy in e-Office reference form, and feedback. */
function SourceList({ statements, nums, api, requestId, onOpenDoc }: {
  statements: ChatStatement[]; nums: Map<string, number>; api?: Api; requestId: string; onOpenDoc?: (cid: string) => void;
}) {
  const rows = [...nums.entries()].map(([cid, n]) => {
    const using = statements.filter((s) => s.citations.some((c) => c.canonical_id === cid));
    const c = using[0].citations.find((x) => x.canonical_id === cid) as ChatCitation;
    const quotes = [...new Set(using.map((s) => s.quote).filter(Boolean))] as string[];
    const conf = using.map((s) => s.confidence).filter(Boolean).sort((a, b) => (a as Confidence).score - (b as Confidence).score)[0] as Confidence | undefined;
    return { cid, n, c, kind: using[0].source, quotes, conf, first: using[0] };
  });
  return (
    <details className="sources-list">
      <summary>Sources ({rows.length})</summary>
      <ol>
        {rows.map((r) => (
          <li key={r.cid} value={r.n}>
            <span className="src-kind">{KIND[r.kind]}: </span>
            <CitePreview api={api} c={r.c} quote={r.quotes[0] ?? null}>
              <button className="cite" onClick={() => onOpenDoc?.(r.cid)}>
                {r.c.reference || r.cid}{r.c.status ? ` (${r.c.status.replace(/_/g, " ")})` : ""}
              </button>
            </CitePreview>
            {r.quotes.map((q) => <q key={q} className="quote">{q}</q>)}
            <span className="src-tools">
              {r.conf && <ConfidenceNote c={r.conf} />}
              <CopyRef s={r.first} />
              {api && <Feedback api={api} choices={THUMBS} target={{ kind: "statement", request_id: requestId, canonical_id: r.cid }} />}
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}

function CopyText({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button className="fb" onClick={() => { void navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }); }}>
      {done ? "Copied" : label}
    </button>
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
