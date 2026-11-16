import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { Api } from "../api";
import type { DraftRow, FilePage, Highlight, PresendReport } from "../types";
import { AssistPanel } from "./AssistPanel";
import { ChatPanel } from "./ChatPanel";
import { CitationLegend, DocumentViewer, HighlightedText } from "./Citations";

/** File inner page (plan §11.2): noting panel · correspondence · C2-24 Assist. */
export function FilePageView({ api, computerNo, open }: { api: Api; computerNo: string; open?: (computerNo: string) => void }) {
  const [page, setPage] = useState<FilePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"toc" | "movements">("toc");
  const [report, setReport] = useState<PresendReport | null>(null);
  const [marks, setMarks] = useState<Record<string, Highlight[]>>({});
  const [files, setFiles] = useState<Map<string, string>>(new Map()); // file no. → comp. no.
  const [viewing, setViewing] = useState<string | null>(null);
  const [help, setHelp] = useState(false);

  // J / K: next / previous pre-send flag; ?: the shortcuts (ADR-0034). Never while typing.
  useEffect(() => {
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
  }, []);

  const load = useCallback(() => {
    api.file(computerNo).then(setPage).catch((e: Error) => setError(e.message));
  }, [api, computerNo]);
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
      <div className="toolbar">
        <button onClick={() => setTab("movements")}>Movements</button>
        <button disabled title="Not in this sandbox slice">Details</button>
        <button disabled title="Not in this sandbox slice">Draft ▾</button>
        <button onClick={send} title="Runs the C2-24 pre-send check; nothing is sent">Send</button>
        <button disabled title="Not in this sandbox slice">Link</button>
        <button disabled title="Not in this sandbox slice">Close ▾</button>
      </div>
      <div className="filehead">
        Comp. No. {f.computer_no} · File No. {f.file_no} · Subject: {f.subject}
        <span className="pill">{f.classification}</span><span className="pill">{f.state}</span>
      </div>
      <div className="panes">
        <section className="noting">
          {Object.values(marks).some((m) => m.length > 0) && <CitationLegend />}
          {page.notes.map((n) => (
            <article key={n.note_id} className={`note ${n.state}`}>
              <h4>Note # {n.note_no} <span className="muted">({n.state === "green" ? "Green note" : "Yellow note — draft"}) · {n.author_post}</span></h4>
              {n.text_source === "needs_ocr"
                ? <p className="muted">Scanned noting — text available after OCR and review.</p>
                : show(n.note_id, n.text)}
            </article>
          ))}
          {page.drafts.map((d) => (
            <DraftCard key={`${d.draft_id}-${d.versions}`} api={api} computerNo={computerNo} d={d}
              view={show(d.draft_id, d.text)} onChanged={load} />
          ))}
          {page.notes.length === 0 && page.drafts.length === 0 && <p className="muted">No notes yet.</p>}
        </section>
        <section className="corr">
          <div className="tabs">
            <button className={tab === "toc" ? "active" : ""} onClick={() => setTab("toc")}>TOC</button>
            <button className={tab === "movements" ? "active" : ""} onClick={() => setTab("movements")}>Movements</button>
          </div>
          {tab === "toc" && page.correspondence.length === 0 && <p className="muted">No correspondence on this file.</p>}
          {tab === "toc" ? (
            page.correspondence.length > 0 && <table className="grid">
              <thead><tr><th>Kind</th><th>Title</th><th>Pages</th></tr></thead>
              <tbody>
                {page.correspondence.map((c) => (
                  <tr key={c.correspondence_id}><td>{c.kind.toUpperCase()}</td><td>{c.title}</td><td>{c.page_from}–{c.page_to}</td></tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table className="grid">
              <thead><tr><th>#</th><th>From</th><th>To</th><th>Sent</th><th>Remarks</th></tr></thead>
              <tbody>
                {page.movements.map((m) => (
                  <tr key={m.seq}><td>{m.seq}</td><td>{m.from_user}</td><td>{m.to_user}</td><td>{m.sent_at.slice(0, 10)}</td><td>{m.remarks}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <AssistPanel api={api} computerNo={computerNo} report={report} onReport={setReport} onInserted={load} onOpenDoc={setViewing} />
        <ChatPanel api={api} computerNo={computerNo} onInserted={load} onOpenDoc={setViewing}
          suggestions={suggestionsFor(marks, page?.file.subject ?? "")} />
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
