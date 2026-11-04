import { useCallback, useEffect, useState } from "react";
import type { Api } from "../api";
import type { FilePage, PresendReport } from "../types";
import { AssistPanel } from "./AssistPanel";

/** File inner page (plan §11.2): noting panel · correspondence · C2-24 Assist. */
export function FilePageView({ api, computerNo }: { api: Api; computerNo: string }) {
  const [page, setPage] = useState<FilePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"toc" | "movements">("toc");
  const [report, setReport] = useState<PresendReport | null>(null);

  const load = useCallback(() => {
    api.file(computerNo).then(setPage).catch((e: Error) => setError(e.message));
  }, [api, computerNo]);
  useEffect(load, [load]);

  if (error) return <p className="error page">{error}</p>;
  if (!page) return <p className="muted page">Opening file…</p>;
  const f = page.file;
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
          {page.notes.map((n) => (
            <article key={n.note_id} className={`note ${n.state}`}>
              <h4>Note # {n.note_no} <span className="muted">({n.state === "green" ? "Green note" : "Yellow note — draft"}) · {n.author_post}</span></h4>
              {n.text_source === "needs_ocr"
                ? <p className="muted">Scanned noting — text available after OCR and review.</p>
                : <pre>{n.text}</pre>}
            </article>
          ))}
          {page.drafts.map((d) => (
            <article key={d.draft_id} className="note yellow">
              <h4>Yellow note — draft <span className="muted">{d.draft_id}</span></h4>
              <p className="ai">AI-assisted draft — inserted by the officer, editable. Not confirmed, signed or sent.</p>
              <pre>{d.text}</pre>
              <div className="actions">
                <button disabled title="Simulated actions come in a later slice">Save</button>
                <button disabled title="Simulated actions come in a later slice">Confirm → Green</button>
              </div>
            </article>
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
        <AssistPanel api={api} computerNo={computerNo} report={report} onReport={setReport} onInserted={load} />
      </div>
    </div>
  );
}
