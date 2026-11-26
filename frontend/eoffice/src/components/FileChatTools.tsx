import { fmtDate } from "../format";
import { useState, type ReactNode } from "react";
import type { Api } from "../api";
import { yellowNoteFrom } from "../presend";
import type { DraftInputs, FileRecords, FileSummary, PreparedDraft, LinkSuggestions, NoteReferences, PresendReport } from "../types";
import {
  BriefCard, ClosingCard, LinkCard, MovementsCard, NoteReferenceCard, PresendCard,
  ReferenceCard, SinceCard, SoFarCard,
} from "./AssistPanel";
import type { FileTool } from "./ChatPanel";
import { insertAfterBody } from "./DraftStudio";

/** What a file's chat can do besides searching (mentor review, 24 Nov 2026; ADR-0064 addendum 1,
 *  ADR-0066): every tool of the Check and Draft tabs, asked by chip or in the officer's words.
 *  Each is read from the file's own scoped endpoint; drafts are made only on the officer's click.
 *  Fixed rules choose the tool (plan §5.6: no model picks it); anything else goes to the scoped
 *  search with the file as context. Order matters: the first rule that matches answers. */
export const FILE_ASKS = {
  dfa: /\b(draft|prepare|write)\b.*\bfor approval\b|\bdfa\b|\bdraft (an? |the )?(order|letter|g\.?o\.?)\b|\b(prepare|write|make|create|generate|give me)\b[^.?]*\bdraft\b(?![^.?]*\b(precedent|first[- ]cut)\b)/i,
  first_cut: /\bfirst[- ]cut\b/i,
  closing: /\bclosing remarks?\b|\bclose (this|the) file\b/i,
  presend: /\bpre-?send\b|\bcheck (this|the) (file|note|draft|noting)\b|\bbefore (i )?send(ing)?\b|\bany conflicts?\b/i,
  related: /\b(related|similar|linked) files?\b|\blink (this|the) file\b/i,
  note_ref: /\b(refer|reference|link)\b.*\b(earlier|previous|old) (note|page|proposal|noting)\b|\bnote\s*#?\s*\d+\b.*\bpara/i,
  reference: /\b(still )?(current|valid|in force)\b/i,
  summary: /\b(summar\w*|overview|gist|so far)\b|what (is|was) (this|the) file about/i,
  movements: /\b(movements?|moved|route|trail|pending with)\b|where is (this|the) file|who (has|holds) (this|the) file/i,
  // a question this file's own notes answer: the last direction, what is pending, who decided
  ask_file: /\bnext (action|step)s?\b|what (should|do|must|shall) i do|\b(i|we) (need|have) to do\b|\bpending\b|last direction|what (was|has been|is) (decided|directed|approved)|who (proposed|approved|decided|signed)/i,
  records: /\b(records?|papers|attachments?|attached)\b.*\b(this|the) file\b|^\s*(show )?(the )?(records|attachments)\b/i,
  brief: /\bapproval brief\b|\bbrief (for|on) approval\b/i,
  since: /\b(changed?|changes) since\b|since the decision/i,
} as const;
export type FileAsk = keyof typeof FILE_ASKS;

/** An order named in the officer's words ("G.O.Ms.No.88/2022", "Circular No. 12 of 2020"). */
const ORDER_REF = /\b(G\.?\s*O\.?\s*(\(?\s*(Ms|Rt|P)\.?\s*\)?)?\.?\s*No\.?\s*\d+[^\s?,]*(\s*(of|dated|dt\.?)\s*[\d./-]+)?|(Circular|Memo(randum)?|Notification|Proceedings)\s*No\.?\s*[\w./-]+(\s*(of|dated|dt\.?)\s*[\d./-]+)?)/i;

/** Which file tool answers this question, or null for the scoped search. */
export function fileAsk(q: string): FileAsk | null {
  for (const k of Object.keys(FILE_ASKS) as FileAsk[]) {
    if (!FILE_ASKS[k].test(q)) continue;
    if (k === "reference" && !ORDER_REF.test(q)) continue; // "current rules on…" is a search question
    return k;
  }
  return null;
}

/** The chips: one per tool, in the officer's order of work. */
const LABELS: [FileAsk, string][] = [
  ["summary", "Summarise this file"], ["ask_file", "What is the next action?"], ["movements", "Movements"], ["records", "Records on this file"],
  ["brief", "Approval brief"], ["since", "Changes since the decision"], ["presend", "Pre-send check"],
  ["related", "Related files"], ["first_cut", "First-cut note"], ["dfa", "Draft for approval"],
  ["closing", "Closing remarks"],
];

export function fileTools({ api, computerNo, onInserted, onOpenDoc, records }: {
  api: Api; computerNo: string; onInserted: () => void; onOpenDoc: (cid: string) => void;
  records: (r: FileRecords) => ReactNode;
}): FileTool[] {
  const run: Record<FileAsk, (asked: string) => Promise<ReactNode>> = {
    summary: (asked) => api.fileSummary(computerNo, asked).then((s) => <SummaryChat s={s} />),
    ask_file: (asked) => api.fileSummary(computerNo, asked).then((s) => <SummaryChat s={s} />),
    movements: () => api.movements(computerNo).then((m) => <MovementsCard m={m} />),
    records: () => api.fileRecords(computerNo).then(records),
    brief: () => api.brief(computerNo).then((b) => <BriefCard b={b} />),
    since: () => api.sinceDecision(computerNo).then((s) => <SinceCard s={s} onOpenDoc={onOpenDoc} />),
    presend: () => api.presend(computerNo).then((r) => <PresendChat api={api} computerNo={computerNo} report={r} onInserted={onInserted} onOpenDoc={onOpenDoc} />),
    related: () => api.linkSuggestions(computerNo).then((s) => <LinkChat api={api} computerNo={computerNo} s={s} onInserted={onInserted} />),
    // a first-cut note written end to end (owner, 26 Nov): the same pipeline as a draft, in a note
    // format chosen from the file's stage (a proposal note; after approval, the note putting up
    // the draft orders) — fields filled from the file's notes, orders that apply, earlier
    // decisions, the pre-send check and checked wording; inserted as a Yellow Note on click
    first_cut: async (asked) => {
      const filled = await api.draftAutofill(computerNo, "auto_note", asked).catch(() => null);
      const format_id = filled?.format_id ?? "note_proposal";
      const d = await api.prepareDraft({
        computer_no: computerNo, format_id, inputs: filled?.inputs ?? {},
        add_references: [], drop_references: [], suggest: true,
      });
      return <DraftChat api={api} computerNo={computerNo} d={d} filled={filled} onInserted={onInserted} />;
    },
    // a draft for approval written in the chosen e-Office format, with Gemini's wording for the
    // officer's gaps (Draft workspace, ADR-0060): the same prepare call as the Draft button
    // end to end (ADR-0067 addendum 4): 1. the model fills the format's inputs from the file's
    // notes (each field gated); 2. the draft is prepared from them with the orders that apply,
    // the pre-send check on the draft and earlier files on the subject, and checked wording for
    // the order paragraphs; 3. the officer edits and saves. The chat message itself is never
    // put into the draft.
    dfa: async (asked) => {
      const asked_for = draftFormat(asked);
      const filled = await api.draftAutofill(computerNo, asked_for, asked).catch(() => null);
      // "auto": the server chose from the file's last direction; without it, a proposal note
      const format_id = filled?.format_id ?? (asked_for === "auto" ? "note_proposal" : asked_for);
      const d = await api.prepareDraft({
        computer_no: computerNo, format_id, inputs: filled?.inputs ?? {},
        add_references: [], drop_references: [], suggest: true,
      });
      return <DraftChat api={api} computerNo={computerNo} d={d} filled={filled} onInserted={onInserted} />;
    },
    closing: () => api.closingRemarks(computerNo).then((c) => <ClosingCard c={c} api={api} onClosed={onInserted} />),
    note_ref: (asked) => api.noteReference(computerNo, asked).then((r) => <NoteRefChat api={api} computerNo={computerNo} r={r} onInserted={onInserted} />),
    reference: (asked) => api.reference(ORDER_REF.exec(asked)?.[0] ?? asked).then((r) => <ReferenceCard r={r} />),
  };
  const label = Object.fromEntries(LABELS) as Partial<Record<FileAsk, string>>;
  return (Object.keys(FILE_ASKS) as FileAsk[]).map((id) => ({ id, label: label[id], match: (q: string) => fileAsk(q) === id, run: run[id] }));
}

/** Which e-Office format the officer's words ask for (config/draft_formats.yaml ids). A "draft
 *  note for approval" is the note that puts up a DFA; an order with no type named is a G.O.Rt. */
export function draftFormat(asked: string): string {
  const q = asked.toLowerCase();
  if (/\bnote\b|\bnoting\b/.test(q)) return "note_dfa";
  if (/\bcircular\b/.test(q)) return "circular_memo";
  if (/\bmemo\b/.test(q)) return "memo";
  if (/\bletter\b/.test(q)) return "letter";
  if (/\bms\b|g\.?o\.?\s*ms|policy|guidelines|rules\b/.test(q)) return "go_ms";
  if (/\border\b|g\.?o\b|g\.?o\.?\s*rt|proceedings/.test(q)) return "go_rt";
  return "auto"; // no kind named: the file's stage decides (server side)
}

/** A prepared draft in the chat: Gemini's suggested wording already put into the officer's gap
 *  (each line checked server side; a removed line is counted), editable, saved only on a click
 *  as a Yellow Note or a DFA draft; the full workspace one click away. */
const FIELD: Record<string, string> = {
  subject: "Subject", request: "Request / reference", facts: "Facts", proposal: "What is ordered",
  signatory: "Signatory", addressees: "To", copy_to: "Copy to",
};

function DraftChat({ api, computerNo, d, filled, onInserted }: {
  api: Api; computerNo: string; d: PreparedDraft; onInserted: () => void;
  filled: { inputs: DraftInputs; sources: Record<string, number[]>; reason: string | null; format_reason?: string | null } | null;
}) {
  const got = Object.keys(filled?.inputs ?? {});
  const gaps = d.format.inputs.filter((f) => !got.includes(f) && f !== "subject");
  const flags = d.checks.flags;
  const precedents = d.related_files ?? [];
  const { busy, error, act } = useAct();
  const wording = d.suggested?.lines.map((l) => l.text).join("\n\n") ?? "";
  const [body, setBody] = useState(wording ? insertAfterBody(d.draft.text, wording) : d.draft.text);
  const [made, setMade] = useState<string | null>(null);
  const yellow = d.draft.saves_as === "yellow_note";
  // e-Office's limits on a draft (the server refuses more): said plainly before trying
  const tooLong = body.length > 20000 || d.draft.citations.length > 50;
  const save = () => void act(
    () => (tooLong
      ? Promise.reject(new Error(`This draft is too long to insert (${body.length.toLocaleString()} characters, ${d.draft.citations.length} sources; the limit is 20,000 characters and 50 sources). Shorten it, then insert.`))
      : (yellow ? api.insertYellowNote : api.createDfa)(computerNo, body, d.draft.citations, d.request_id)),
    (r) => { setMade(r.draft_id); onInserted(); },
  );
  return (
    <div className="assist draft-chat">
      <p className="answer-lead">
        I've prepared a draft for this file: {d.format.title}.
        {filled?.format_reason ? ` ${filled.format_reason}` : ""}
        {gaps.length === 0 ? " It is filled from the notes; read it through, edit as needed and save." : " Check the marked gaps before saving."}
      </p>
      {filled?.format_reason && <p className="muted small">Need a different kind? Ask for a G.O., memo, letter, circular or note.</p>}
      <h4>{d.format.title} — draft</h4>
      {d.suggested?.fallback && <p className="muted small">The suggested wording is not available now ({d.suggested.reason ?? "model unavailable"}); the format is filled from the file and the gaps are marked for you.</p>}
      {d.suggested && d.suggested.removed > 0 && <p className="muted small">{d.suggested.removed} suggested line(s) were removed: not supported by the records.</p>}
      {got.length > 0 && (
        <p className="small draft-filled">Filled from the file: {got.map((f) => (
          <span key={f} className="p-chip">{FIELD[f] ?? f}{filled?.sources[f]?.length ? ` · Note #${filled.sources[f].join(", #")}` : ""}</span>
        ))}</p>
      )}
      {!got.length && filled?.reason && <p className="muted small">The inputs could not be filled automatically ({filled.reason}); the gaps are marked in the draft.</p>}
      {gaps.length > 0 && <p className="muted small">For you to complete: {gaps.map((f) => FIELD[f] ?? f).join(", ")}.</p>}
      <textarea className="draft-text" value={body} onChange={(e) => setBody(e.target.value)} rows={14} aria-label="Draft text" disabled={!!made} />
      <div className="actions">
        <button className="primary" disabled={busy || !!made} onClick={save}>{yellow ? "Insert as Yellow Note" : "Create DFA draft"}</button>
        <a className="button-like" href={`#/draft/${encodeURIComponent(computerNo)}/${d.format.id}`}>Open in the draft workspace</a>
      </div>
      {made && <p className="ok">Saved as draft {made}. It is in the Notes tab as your Yellow Note: edit, then sign it or send the file.</p>}
      <Err e={error} />
      <div className={`draft-checks${flags.length ? " warn" : ""}`}>
        <strong>{flags.length ? `${flags.length} point(s) to check before putting up` : "No conflict found in the records you may see"}</strong>
        {flags.length > 0 && <ul>{flags.map((f, i) => <li key={i}><b>{f.type}</b> {f.explanation}</li>)}</ul>}
        {d.checks.status_unconfirmed.length > 0 && <p className="muted small">Status not confirmed from your records: {d.checks.status_unconfirmed.join(" · ")}</p>}
        {d.checks.authority_message && <p className="muted small">{d.checks.authority_message}</p>}
      </div>
      {d.read_list.length > 0 && <p className="muted small">Orders read: {d.read_list.map((r) => r.label || r.canonical_id).join("; ")}</p>}
      {precedents.length > 0 && (
        <p className="muted small">Earlier files on this subject: {precedents.slice(0, 5).map((p, i) => (
          <span key={p.computer_no}>{i > 0 && " · "}<a href={`#/file/${encodeURIComponent(p.computer_no)}`}>{p.file_no}</a></span>
        ))}</p>
      )}
    </div>
  );
}

/** "Summarise this file": the written summary first (each point with the notes it rests on),
 *  the notes in full folded under it; without a summary, the notes as before. */
const SECTIONS: [string, string][] = [
  ["about", "What this file is about"], ["history", "What happened"], ["decision", "Decisions and directions"],
  ["status", "Where the file stands"], ["pending", "What is pending"], ["other", "Other details"],
];

export function SummaryChat({ s }: { s: FileSummary }) {
  if (!s.summary) return <SoFarCard s={s} />;
  // note 0 is the e-Office record itself (state, holder, last direction), not a note
  const Notes = ({ nos }: { nos: number[] }) => (
    <>{nos.map((n) => (
      <sup key={n}><span className="cn note-ref" title={n === 0 ? "e-Office record" : `Note #${n}`}>
        {n === 0 ? "record" : `#${n}`}
      </span></sup>
    ))}</>
  );
  const facts = s.facts ?? [];
  // a full summary comes in parts; where the file stands is e-Office's own record, never the model's
  const structured = s.summary.points.some((p) => p.section);
  const stands = facts.filter((t) => !/^(This file is about|Correspondence placed|No correspondence)/.test(t));
  return (
    <div className="file-summary">
      {s.summary.lead
        ? <p className="answer-lead">{s.summary.lead}<Notes nos={s.summary.lead_notes} /></p>
        : facts.length > 0 && (
          // the written reply did not pass the checks: what e-Office records, in plain sentences
          <p className="answer-lead">{facts.slice(0, 4).join(" ")}<sup><span className="cn note-ref" title="e-Office record">record</span></sup></p>
        )}
      {structured ? (
        <>
          {SECTIONS.map(([key, title]) => {
            if (key === "status") {
              return stands.length > 0 && (
                <section key={key} className="summary-part">
                  <h5>{title}</h5>
                  <ul className="answer-points">
                    {stands.map((t) => <li key={t}>{t}<Notes nos={[0]} /></li>)}
                  </ul>
                </section>
              );
            }
            const pts = s.summary!.points.filter((p) => (p.section ?? "other") === key);
            return pts.length > 0 && (
              <section key={key} className="summary-part">
                <h5>{title}</h5>
                <ul className="answer-points">
                  {pts.map((p, i) => <li key={i}>{p.text}<Notes nos={p.notes} /></li>)}
                </ul>
              </section>
            );
          })}
        </>
      ) : s.summary.points.length > 0 && (
        <ul className="answer-points">
          {s.summary.points.map((p, i) => <li key={i}>{p.text}<Notes nos={p.notes} /></li>)}
        </ul>
      )}
      {s.pending_message && <p className="muted small">{s.pending_message}</p>}
      <details className="sources-list">
        <summary>The notes in full ({s.notes.length})</summary>
        <div className="notes-full">
          {s.notes.map((n) => (
            <div key={n.note_no} className={`note-full${n.note_no === s.last_direction ? " last" : ""}`}>
              <strong>Note #{n.note_no}</strong> · {n.post ?? "post not stated"}
              {n.signed_at && <>, {fmtDate(n.signed_at)}</>}
              {n.note_no === s.last_direction && <span className="badge">last direction</span>}
              <p>{n.text}</p>
            </div>
          ))}
          {s.gap_message && <p className="muted small">{s.gap_message}</p>}
        </div>
      </details>
    </div>
  );
}

// ---- the stateful cards: each keeps its own edits and "made" state inside the conversation ----

function useAct() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const act = async <T,>(f: () => Promise<T>, then: (x: T) => void) => {
    setBusy(true); setError(null);
    try { then(await f()); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return { busy, error, act };
}

const Err = ({ e }: { e: string | null }) => (e ? <p className="error">{e}</p> : null);

function PresendChat({ api, computerNo, report, onInserted, onOpenDoc }: {
  api: Api; computerNo: string; report: PresendReport; onInserted: () => void; onOpenDoc: (cid: string) => void;
}) {
  const { busy, error, act } = useAct();
  const [inserted, setInserted] = useState<string | null>(null);
  const insert = () => {
    const { body, citations } = yellowNoteFrom(report);
    void act(() => api.insertYellowNote(computerNo, body, citations, report.request_id), (r) => { setInserted(r.draft_id); onInserted(); });
  };
  return <div className="assist"><PresendCard api={api} computerNo={computerNo} report={report} busy={busy} inserted={inserted} onInsert={insert} onOpenDoc={onOpenDoc} /><Err e={error} /></div>;
}


function LinkChat({ api, computerNo, s, onInserted }: { api: Api; computerNo: string; s: LinkSuggestions; onInserted: () => void }) {
  const { busy, error, act } = useAct();
  const [linked, setLinked] = useState<Record<string, string>>({});
  return (
    <div className="assist">
      <LinkCard s={s} linked={linked} busy={busy}
        onLink={(fileNo, citations) => void act(() => api.suggestLink(computerNo, fileNo, citations, s.request_id), (r) => { setLinked((m) => ({ ...m, [fileNo]: r.draft_id })); onInserted(); })} />
      <Err e={error} />
    </div>
  );
}

function NoteRefChat({ api, computerNo, r, onInserted }: { api: Api; computerNo: string; r: NoteReferences; onInserted: () => void }) {
  const { busy, error, act } = useAct();
  const [done, setDone] = useState<Record<string, string>>({});
  return (
    <div className="assist">
      <NoteReferenceCard r={r} done={done} busy={busy}
        onInsert={(sg) => void act(() => api.insertReference(computerNo, sg, r.request_id), (d) => {
          setDone((m) => ({ ...m, [sg.target_id + ":" + (sg.paragraph ?? sg.page_from)]: d.draft_id })); onInserted();
        })} />
      <Err e={error} />
    </div>
  );
}
