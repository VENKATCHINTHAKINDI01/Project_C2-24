import { useState } from "react";
import type { Api } from "../api";
import { FLAG_NAMES, outcomeLabel, yellowNoteFrom } from "../presend";
import type { FileSoFar, PresendReport, ReferenceResult } from "../types";

/** C2-24 Assist for the open file (plan §11.5 touchpoints 10, 11). Drafts only. */
export function AssistPanel({ api, computerNo, report, onReport, onInserted }: {
  api: Api; computerNo: string; report: PresendReport | null;
  onReport: (r: PresendReport) => void; onInserted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refText, setRefText] = useState("");
  const [ref, setRef] = useState<ReferenceResult | null>(null);
  const [inserted, setInserted] = useState<string | null>(null);
  const [soFar, setSoFar] = useState<FileSoFar | null>(null);

  const run = async <T,>(f: () => Promise<T>, then: (x: T) => void) => {
    setBusy(true); setError(null);
    try { then(await f()); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const insert = () => {
    if (!report) return;
    const { body, citations } = yellowNoteFrom(report);
    void run(() => api.insertYellowNote(computerNo, body, citations, report.request_id), (r) => {
      setInserted(r.draft_id); onInserted();
    });
  };

  return (
    <aside className="assist">
      <h3>✦ C2-24 Assist — this file</h3>
      <div className="chips">
        <button disabled={busy} onClick={() => void run(() => api.fileSoFar(computerNo), setSoFar)}>File so far</button>
        <button disabled={busy} onClick={() => void run(() => api.presend(computerNo), onReport)}>Pre-send check</button>
      </div>

      <form className="refbox" onSubmit={(e) => { e.preventDefault(); if (refText.trim()) void run(() => api.reference(refText), setRef); }}>
        <label htmlFor="ref">Local reference — is this order still current?</label>
        <div className="row">
          <input id="ref" value={refText} maxLength={300} placeholder="e.g. G.O.Ms.No.88/2022" onChange={(e) => setRefText(e.target.value)} />
          <button disabled={busy || !refText.trim()}>Check</button>
        </div>
      </form>
      {ref && <ReferenceCard r={ref} />}

      {error && <p className="error">{error}</p>}
      {soFar && <SoFarCard s={soFar} />}

      {report && (
        <section>
          <h4 className={report.outcome === "conflicts_found" ? "warn" : ""}>{outcomeLabel(report)}</h4>
          {report.message && <p className="card">{report.message}</p>}
          {report.flags?.map((f, i) => (
            <div key={i} className="flag">
              <div className="flag-head">
                <strong>{f.type} · {FLAG_NAMES[f.type]}</strong>
                <span className={f.certain ? "badge" : "badge soft"}>{f.certain ? "from records" : "uncertain"}</span>
              </div>
              <p>{f.explanation}</p>
              {f.evidence_ids.length > 0 && <p className="src">Sources: {f.evidence_ids.join(" · ")}</p>}
            </div>
          ))}
          {!!report.status_unconfirmed?.length && (
            <p className="card">Status not confirmed from your records: {report.status_unconfirmed.join(" · ")}</p>
          )}
          {!!report.fact_gaps?.length && <p className="card">Not stated clearly in the note: {report.fact_gaps.join(", ")}</p>}
          {report.authority_message && <p className="card">{report.authority_message}</p>}
          <Caveats calibrated={report.calibrated} mockRules={report.mock_rules} />
          {!!report.flags?.length && (
            <div className="actions">
              <button className="primary" disabled={busy || inserted !== null} onClick={insert}>Insert as Yellow Note</button>
              {inserted && <span className="muted">Draft {inserted} added to the noting panel.</span>}
            </div>
          )}
        </section>
      )}
      <p className="footnote">Drafts only. Nothing is saved, signed or sent without the officer.</p>
    </aside>
  );
}

/** Touchpoint 8: the note chain by post. Each note in its own words with its source; gaps named. */
export function SoFarCard({ s }: { s: FileSoFar }) {
  return (
    <section className="sofar">
      <h4>File so far — {s.file_no}</h4>
      {s.chain.length > 0 && <p className="muted">By post: {s.chain.join(" → ")}</p>}
      {s.notes.length === 0 && <p className="card">No notes in this file are available to you yet.</p>}
      <ol className="chain">
        {s.notes.map((n) => (
          <li key={n.note_no} className={n.note_no === s.last_direction ? "last" : ""}>
            <strong>Note #{n.note_no}</strong> · {n.post ?? "post not stated"}
            {n.signed_at && <> · {n.signed_at.slice(0, 10)}</>}
            {n.note_no === s.last_direction && <span className="badge">last direction</span>}
            <p>{n.text}</p>
            <p className="src">Source: {n.source}</p>
          </li>
        ))}
      </ol>
      {s.gap_message && <p className="card">{s.gap_message}</p>}
      {s.pending_message && <p className="card">{s.pending_message}</p>}
    </section>
  );
}

function ReferenceCard({ r }: { r: ReferenceResult }) {
  if (r.choices?.length) return <p className="card">More than one order matches — which one? {r.choices.join(" · ")}</p>;
  if (!r.found) return <p className="card">{r.message}</p>;
  const d = r.documents?.[0];
  return (
    <div className="card">
      {d && <p><strong>{d.canonical_id}</strong> — {d.subject}</p>}
      {r.status && <p>Status: <strong>{r.status.replace(/_/g, " ")}</strong>{r.by ? <> by <strong>{r.by}</strong></> : null}</p>}
      {r.current_version && r.current_version !== d?.canonical_id && <p>Current version: <strong>{r.current_version}</strong></p>}
      {r.message && <p className="muted">{r.message}</p>}
    </div>
  );
}

function Caveats({ calibrated, mockRules }: { calibrated: boolean; mockRules: boolean }) {
  return (
    <ul className="caveats">
      {mockRules && <li>Approval rules are mock (testing only): authority flags are prompts to check, not guidance.</li>}
      {!calibrated && <li>Search thresholds are sandbox demo values, not calibrated.</li>}
    </ul>
  );
}
