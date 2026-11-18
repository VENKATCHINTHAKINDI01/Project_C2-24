import { useState } from "react";
import { fmtDate } from "../format";
import type { Api } from "../api";
import type { SearchResult } from "../types";

/** Advance search in plain language, within the officer's search scope (touchpoint 15). */
export function SearchPage({ api }: { api: Api }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<SearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true); setError(null);
    api.search(q).then(setRes).catch((err: Error) => setError(err.message)).finally(() => setBusy(false));
  };
  return (
    <main className="page">
      <h1>Advance search</h1>
      <p className="muted">Describe what you are looking for in your own words: a subject, an order number, a year. Only records you may open are searched.</p>
      <form onSubmit={submit} className="row searchrow">
        <input aria-label="What are you looking for?" value={q} maxLength={500} placeholder="e.g. spouse transfer requests decided in 2023" onChange={(e) => setQ(e.target.value)} />
        <button className="primary" disabled={busy || !q.trim()}>{busy ? "Searching…" : "Search"}</button>
      </form>
      {!res && !busy && (
        <div className="examples">
          <span className="muted">Try:</span>
          {["G.O.Ms.No.88/2022", "that 2023 drain case", "spouse ground transfer precedent"].map((x) => (
            <button key={x} type="button" className="linkish" onClick={() => setQ(x)}>{x}</button>
          ))}
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {res && (
        <>
          <p className="muted">
            {res.documents.length} record(s){res.files.length ? ` on ${res.files.length} file(s): ${res.files.join(", ")}` : ""}.
            {!res.calibrated && " Search thresholds are demo values, not calibrated."}
          </p>
          <table className="grid register">
            <thead><tr><th>Document</th><th>Type</th><th>Date</th><th>Subject</th><th>File No.</th></tr></thead>
            <tbody>
              {res.documents.map((d) => (
                <tr key={d.canonical_id}><td>{d.canonical_id}</td><td>{d.doc_type}</td><td className="date">{fmtDate(d.issue_date)}</td><td>{d.subject}</td><td>{d.file_no ?? ""}</td></tr>
              ))}
            </tbody>
          </table>
          {res.documents.length === 0 && <p className="muted">No sufficiently supported result in the records available to you.</p>}
        </>
      )}
    </main>
  );
}
