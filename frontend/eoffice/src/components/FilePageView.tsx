import { useCallback, useEffect, useState, type ReactNode } from "react";
import { fmtDateTime } from "../format";
import type { Api } from "../api";
import type { DfaRow, DraftRow, FilePage, FileRecords, Highlight, PresendReport, Standing } from "../types";
import { usePrefs } from "../prefs";
import { AssistPanel } from "./AssistPanel";
import { ChatPanel } from "./ChatPanel";
import { CitationLegend, DocumentViewer, HighlightedText } from "./Citations";

/** File inner page (plan §11.2): noting panel · correspondence · C2-24 Assist. */
export function FilePageView({ api, computerNo, open, draft }: {
  api: Api; computerNo: string; open?: (computerNo: string) => void; draft?: () => void;
}) {
  const [page, setPage] = useState<FilePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"toc" | "movements" | "records">("toc");
  const [records, setRecords] = useState<FileRecords | null>(null);
  const [attaching, setAttaching] = useState<string | null>(null);
  const [report, setReport] = useState<PresendReport | null>(null);
  const [marks, setMarks] = useState<Record<string, Highlight[]>>({});
  const [files, setFiles] = useState<Map<string, string>>(new Map()); // file no. → comp. no.
  const [viewing, setViewing] = useState<string | null>(null);
  const [help, setHelp] = useState(false);
  const prefs = usePrefs();
  const [assistOpen, setAssistOpen] = useState(prefs.assistant_panel === "open");

  // J / K: next / previous pre-send flag; ?: the shortcuts (ADR-0034). Never while typing.
  useEffect(() => {
    if (!prefs.shortcuts) return undefined; // switched off in Settings
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.ctrlKey || e.metaKey || e.altKey || (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      if (e.key === "?") { setHelp((h) => !h); return; }
      if (e.key !== "j" && e.key !== "k") return;
      const flags = Array.from(document.querySelectorAll<HTMLElement>(".flag[data-flag]"));
      if (!flags.length) return;
      const at = flags.indexOf(document.activeElement as HTMLElement);
      const next = e.key === "j" ? Math.min(flags.length - 1, at + 1) : Math.max(0, at < 0 ? 0 : at - 1);
      flags[next].focus();
      flags[next].scrollIntoView({ block: "nearest", behavior: "smooth" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [prefs.shortcuts]);

  const load = useCallback(() => {
    api.file(computerNo).then(setPage).catch((e: Error) => setError(e.message));
    // what of this file is in institutional memory; a help, not the page
    api.fileRecords(computerNo).then(setRecords).catch(() => setRecords(null));
  }, [api, computerNo]);
  const attach = (file: File | undefined) => {
    if (!file) return;
    setAttaching(`Attaching ${file.name}…`);
    api.attach(computerNo, file)
      .then(() => { setAttaching(null); setTab("records"); load(); })
      .catch((e: Error) => setAttaching(`Not attached: ${e.message}`));
  };
  useEffect(load, [load]);
  useEffect(() => {
    api.files().then((r) => setFiles(new Map(r.files.map((f) => [f.file_no, f.computer_no])))).catch(() => setFiles(new Map()));
  }, [api]);
  useEffect(() => {
    if (!page) return;
    const texts = [
      ...page.notes.filter((n) => n.text).map((n) => ({ note_id: n.note_id, text: n.text ?? "" })),
      ...page.drafts.filter((d) => d.text).map((d) => ({ note_id: d.draft_id, text: d.text ?? "" })),
    ];
    if (texts.length === 0) return;
    // Highlights are a help, not the page: if they fail, the notes still show as written.
    api.highlights(computerNo, texts)
      .then((h) => setMarks(Object.fromEntries(h.notes.map((n) => [n.note_id, n.highlights]))))
      .catch(() => setMarks({}));
  }, [api, computerNo, page]);

  if (error) return <p className="error page">{error}</p>;
  if (!page) return <p className="muted page">Opening file…</p>;
  const f = page.file;
  const fileNos = new Set(files.keys());
  const show = (id: string, text: string | null) => (
    <HighlightedText text={text ?? ""} highlights={marks[id] ?? []} onOpenDoc={setViewing}
      onOpenFile={(no) => { const c = files.get(no); if (c && open) open(c); }} fileNos={open ? fileNos : new Set()} />
  );
  const send = () => { void api.presend(computerNo).then(setReport).catch((e: Error) => setError(e.message)); };

  return (
    <div className="filepage">
      <header className="filecover">
        <div className="cover-main">
          <p className="cover-no">File No. <strong>{f.file_no}</strong></p>
          <h1 className="cover-subject">{f.subject}</h1>
          <dl className="cover-meta">
            <div><dt>Computer No.</dt><dd>{f.computer_no}</dd></div>
            <div><dt>Section</dt><dd>{f.dealing_section}</dd></div>
            <div><dt>Category</dt><dd>{f.category}</dd></div>
            <div><dt>State</dt><dd>{f.state === "closed" ? "Closed" : "Open"}</dd></div>
            {f.previous_references.length > 0 && <div><dt>Previous references</dt><dd>{f.previous_references.join(", ")}</dd></div>}
          </dl>
        </div>
        <span className={`stamp ${f.classification.toLowerCase()}`} aria-label={`Classification: ${f.classification}`}>{f.classification}</span>
      </header>
      <div className="toolbar" role="toolbar" aria-label="File actions">
        <button onClick={() => setTab("movements")}>Movements</button>
        <button onClick={send} title="Runs the C2-24 pre-send check; nothing is sent">Send</button>
        {draft && <button onClick={draft} title="Prepare a note or an order in a chosen format">Draft</button>}
        {f.state !== "closed" && (
          <label className="button-like" title="Attach a paper (PDF, Word, text or image). It is read and added to the records; a scan waits for OCR review.">
            Attach
            <input type="file" hidden accept=".pdf,.docx,.txt,.jpg,.jpeg,.png,.heic,.tif,.tiff"
              onChange={(e) => { attach(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
        )}
        <span className="toolbar-off" title="e-Office actions this sandbox does not simulate">
          <button disabled>Link</button><button disabled>Park</button>
        </span>
        <button className="assist-toggle" aria-expanded={assistOpen} onClick={() => setAssistOpen((o) => !o)}>
          {assistOpen ? "Hide assistant" : "Show assistant"}
        </button>
      </div>
      <div className={`panes${assistOpen ? "" : " solo"}`}>
        <section className="noting">
          {Object.values(marks).some((m) => m.length > 0) && <CitationLegend />}
          {page.notes.map((n) => (
            <article key={n.note_id} className={`note ${n.state}`}>
              <h4><span className="note-no">Note #{n.note_no}</span> <span className="note-kind">{n.state === "green" ? "Green Note" : "Yellow Note (draft)"}</span><span className="note-by">{n.author_post}</span></h4>
              {n.text_source === "needs_ocr"
                ? <p className="muted">Scanned noting — text available after OCR and review.</p>
                : show(n.note_id, n.text)}
            </article>
          ))}
          {page.drafts.map((d) => (
            <DraftCard key={`${d.draft_id}-${d.versions}`} api={api} computerNo={computerNo} d={d}
              view={show(d.draft_id, d.text)} onChanged={load} />
          ))}
          {(page.awaiting_approval ?? []).map((d) => (
            <ApprovalCard key={d.draft_id} api={api} computerNo={computerNo} d={d} onChanged={load} />
          ))}
          {(page.submitted ?? []).map((d) => <SubmittedCard key={d.draft_id} d={d} />)}
          {page.notes.length === 0 && page.drafts.length === 0 && <p className="muted">No notes yet.</p>}
        </section>
        <section className="corr">
          <div className="tabs">
            <button className={tab === "toc" ? "active" : ""} onClick={() => setTab("toc")}>Correspondence</button>
            <button className={tab === "movements" ? "active" : ""} onClick={() => setTab("movements")}>Movements</button>
            <button className={tab === "records" ? "active" : ""} onClick={() => setTab("records")}>Records</button>
          </div>
          {attaching && <p className="busy" role="status">{attaching}</p>}
          {tab === "toc" && page.correspondence.length === 0 && <p className="muted">No correspondence on this file.</p>}
          {tab === "records" ? <RecordsTab records={records} attachments={page.attachments ?? []} view={setViewing} /> : tab === "toc" ? (
            page.correspondence.length > 0 && <table className="grid">
              <thead><tr><th>Type</th><th>Title</th><th className="num">Pages</th></tr></thead>
              <tbody>
                {page.correspondence.map((c) => (
                  <tr key={c.correspondence_id}><td><abbr title={c.kind === "puc" ? "Paper under consideration" : "Fresh receipt"}>{c.kind.toUpperCase()}</abbr></td><td>{c.title}</td><td className="num">{c.page_from}–{c.page_to}</td></tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table className="grid">
              <thead><tr><th className="num">#</th><th>From</th><th>To</th><th>Sent on</th><th>Remarks</th></tr></thead>
              <tbody>
                {page.movements.map((m) => (
                  <tr key={m.seq}>
                    <td className="num">{m.seq}</td><td>{m.from_post ?? m.from_user}</td><td>{m.to_post ?? m.to_user}</td>
                    <td className="date">{fmtDateTime(m.sent_at)}</td>
                    <td>{m.remarks}{m.sent_back && <span className="tag">sent back</span>}</td>
                  </tr>
                ))}
                {page.movements.length === 0 && <tr><td colSpan={5} className="muted">The file has not moved yet.</td></tr>}
              </tbody>
            </table>
          )}
        </section>
        <div className="assistcol" hidden={!assistOpen}>
          <AssistPanel api={api} computerNo={computerNo} report={report} onReport={setReport} onInserted={load} onOpenDoc={setViewing} />
          <ChatPanel api={api} computerNo={computerNo} onInserted={load} onOpenDoc={setViewing}
            suggestions={suggestionsFor(marks, page?.file.subject ?? "")} />
        </div>
      </div>
      {viewing && <DocumentViewer api={api} canonicalId={viewing} onClose={() => setViewing(null)} />}
      {help && (
        <div className="shortcuts" role="dialog" aria-label="Keyboard shortcuts" onClick={() => setHelp(false)}>
          <h4>Keyboard shortcuts</h4>
          <dl>
            <dt>Ctrl / ⌘ + K</dt><dd>Ask C2-24</dd>
            <dt>Ctrl / ⌘ + Enter</dt><dd>Insert the latest first-cut note as a Yellow Note (a draft)</dd>
            <dt>J / K</dt><dd>Next / previous pre-send flag</dd>
            <dt>?</dt><dd>Show or hide this list</dd>
          </dl>
        </div>
      )}
    </div>
  );
}

const EVENT: Record<string, string> = {
  file_created: "file opened", attachment_added: "attached", note_confirmed: "note confirmed",
  draft_dispatched: "order issued", file_closed: "file closed", order_received: "order received",
  receipt_diarised: "receipt diarised", loaded: "loaded",
};
const STANDING_TEXT: Record<Standing, string> = {
  in_force: "In force", superseded: "Superseded", repealed: "Repealed", expired: "Expired",
  not_yet_in_force: "Not yet in force", unconfirmed: "Status not confirmed", not_an_order: "",
};

/** ADR-0045: what of this file entered institutional memory (only official acts: the file's
 *  particulars, attached papers, confirmed notes, issued orders), and what still waits. */
function RecordsTab({ records, attachments, view }: {
  records: FileRecords | null; attachments: { attachment_id: string; filename: string; uploaded_by_post: string | null; uploaded_at: string }[];
  view: (cid: string) => void;
}) {
  if (!records) return <p className="muted">Not available.</p>;
  return (
    <div className="records">
      <p className="muted">Drafts are not here: a note enters when it is confirmed, an order when it is issued.</p>
      <table className="grid">
        <thead><tr><th>Record</th><th>Status</th><th>History</th><th /></tr></thead>
        <tbody>
          {records.records.map((r) => (
            <tr key={r.canonical_id}>
              <td><strong>{r.doc_type}</strong><br /><span className="muted small">{r.subject}</span></td>
              <td>{STANDING_TEXT[r.standing] && <span className={`pill ${r.standing === "in_force" ? "ok" : "bad"}`}>{STANDING_TEXT[r.standing]}</span>}</td>
              <td className="small">{r.versions > 1 ? `${r.versions} versions · ` : ""}{r.last_event ? EVENT[r.last_event] ?? r.last_event : ""}</td>
              <td><button className="link" onClick={() => view(r.canonical_id)}>Preview</button></td>
            </tr>
          ))}
          {records.records.length === 0 && <tr><td colSpan={4} className="muted">Nothing of this file is in the records yet.</td></tr>}
        </tbody>
      </table>
      {records.waiting.length > 0 && (
        <>
          <h4>Waiting</h4>
          <ul className="waiting">{records.waiting.map((w) => <li key={w.filename}><strong>{w.filename}</strong>: waiting for {w.waiting_for.join(", ")}</li>)}</ul>
        </>
      )}
      {attachments.length > 0 && (
        <>
          <h4>Attached papers</h4>
          <ul className="waiting">{attachments.map((a) => <li key={a.attachment_id}>{a.filename} <span className="muted small">— {a.uploaded_by_post ?? ""}, {fmtDateTime(a.uploaded_at)}</span></li>)}</ul>
        </>
      )}
    </div>
  );
}

/** A DFA another officer put up to you (ADR-0045): approving is your e-Office act, simulated here
 *  (no DSC/eSign); it numbers, dates and issues the order, which then enters the records. */
function ApprovalCard({ api, computerNo, d, onChanged }: { api: Api; computerNo: string; d: DfaRow; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const act = (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    fn().then(onChanged).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  return (
    <article className="note approval">
      <h4>For your approval <span className="muted">put up by {d.author_post ?? "an officer"}</span></h4>
      <pre className="draft-text">{d.text}</pre>
      <div className="actions">
        <button className="primary" disabled={busy}
          title="Your approval and signature (simulated). The order is numbered, dated and issued, and enters the records."
          onClick={() => act(() => api.approveAndIssue(computerNo, d.draft_id))}>Approve, sign and issue</button>
        <button disabled={busy} onClick={() => act(() => api.returnDraft(computerNo, d.draft_id))}>Return for changes</button>
      </div>
      {error && <p className="error">{error}</p>}
    </article>
  );
}

function SubmittedCard({ d }: { d: DfaRow }) {
  return (
    <article className="note submitted">
      <h4>{d.status === "dispatched" ? `Issued: ${d.issued_as ?? ""}` : "Put up for approval"}
        <span className="muted">{d.status === "dispatched" ? ` approved by ${d.approved_by_post ?? ""}` : " waiting for the approving officer"}</span></h4>
      {d.status !== "dispatched" && <p className="muted small">You can no longer edit it unless it is returned.</p>}
    </article>
  );
}

const DRAFT_TITLE: Record<string, string> = {
  suggested_reference: "Suggested reference — draft",
  dfa_draft: "DFA — draft",
  yellow_note: "Yellow note — draft",
};

/** The officer's own draft in e-Office (plan §9.1 checkpoint 2): edit, then confirm as the next
 *  Green Note (simulated signature — no DSC/eSign) or discard. Only the author sees it. Confirming
 *  is the officer's e-Office action, not the assistant's. */
function DraftCard({ api, computerNo, d, view, onChanged }: {
  api: Api; computerNo: string; d: DraftRow; view: ReactNode; onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(d.text ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const act = (f: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    f().then(() => { setEditing(false); onChanged(); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };
  return (
    <article className="note yellow">
      <h4>{DRAFT_TITLE[d.kind] ?? "Draft"} <span className="muted">{d.draft_id} · version {d.versions}</span></h4>
      <p className="ai">AI-assisted draft — inserted by you, editable, visible only to you. Not confirmed, signed or sent.</p>
      {editing
        ? <textarea aria-label="Edit draft" value={text} rows={12} onChange={(e) => setText(e.target.value)} />
        : view}
      <div className="actions">
        {editing
          ? <button disabled={busy || !text.trim()} onClick={() => act(() => api.saveDraft(computerNo, d.draft_id, text))}>Save</button>
          : <button disabled={busy} onClick={() => setEditing(true)}>Edit</button>}
        {d.kind === "dfa_draft" && (
          <button className="primary" disabled={busy || editing}
            title="Put the draft up to the approving officer. You can no longer edit it unless it is returned."
            onClick={() => act(() => api.submitDraft(computerNo, d.draft_id))}>Put up for approval</button>
        )}
        {d.kind === "yellow_note" && (
          <button className="primary" disabled={busy || editing}
            title="Your confirmation (simulated signature). The AI watermark is removed; the note becomes the file's next Green Note."
            onClick={() => act(() => api.confirmDraft(computerNo, d.draft_id))}>Confirm → Green</button>
        )}
        <button disabled={busy} onClick={() => act(() => api.discardDraft(computerNo, d.draft_id))}>Discard</button>
      </div>
      {error && <p className="error">{error}</p>}
    </article>
  );
}

/** The matter a file is about, from its subject line: "Establishment – Sri X – Request for
 *  transfer … on spouse grounds – Reg." → "request for transfer … on spouse grounds". */
export function topicOf(subject: string): string {
  const parts = subject.split(/\s[–—-]\s/).map((p) => p.trim()).filter((p) => p && !/^reg\.?$/i.test(p));
  const t = (parts[parts.length - 1] ?? "").replace(/\.$/, "");
  return t ? t.charAt(0).toLowerCase() + t.slice(1) : "";
}

/** Questions this file invites (ADR-0034), in words the assistant answers well: about the file's
 *  own matter, and "is it still in force?" for each order cited in the notes that the check marked
 *  (at most two), in the words the note used. */
export function suggestionsFor(marks: Record<string, Highlight[]>, subject: string): string[] {
  const topic = topicOf(subject);
  const flagged = [...new Set(Object.values(marks).flat()
    .filter((h) => h.kind === "order" && (h.state === "conflict" || h.state === "review"))
    .map((h) => h.raw.trim()))].slice(0, 2);
  return [
    ...(topic ? [`Has a ${topic} been decided before?`, `What are the current rules on ${topic}?`] : []),
    ...flagged.map((raw) => `Is ${raw} still in force?`),
    "Draft the noting using that precedent.",
  ];
}
