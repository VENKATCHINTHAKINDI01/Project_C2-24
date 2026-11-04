import { useState } from "react";
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
      <h2>Advance search</h2>
      <form onSubmit={submit} className="row">
        <input value={q} maxLength={500} placeholder='e.g. "that 2023 drain case"' onChange={(e) => setQ(e.target.value)} />
        <button disabled={busy || !q.trim()}>Search</button>
      </form>
      {error && <p className="error">{error}</p>}
      {res && (
        <>
          <p className="muted">
            Files: {res.files.length ? res.files.join(" · ") : "none"} · answered at {res.ladder_level ?? "—"}
            {!res.calibrated && " · demo thresholds, not calibrated"}
          </p>
          <table className="grid">
            <thead><tr><th>Document</th><th>Type</th><th>Date</th><th>Subject</th><th>File No.</th></tr></thead>
            <tbody>
              {res.documents.map((d) => (
                <tr key={d.canonical_id}><td>{d.canonical_id}</td><td>{d.doc_type}</td><td>{d.issue_date ?? ""}</td><td>{d.subject}</td><td>{d.file_no ?? ""}</td></tr>
              ))}
            </tbody>
          </table>
          {res.documents.length === 0 && <p className="muted">No sufficiently supported result in the records available to you.</p>}
        </>
      )}
    </main>
  );
}
