import { useEffect, useState } from "react";
import type { Api } from "../api";
import { FLAG_NAMES } from "../presend";
import type { Diarise, DiaryPrefill, Notices, ReceiptReview, ReceiptRow } from "../types";

const CHANGE: Record<string, string> = { SUPERSEDES: "supersedes", REPEALS: "repeals", AMENDS: "amends" };

/** Touchpoint 4: an incoming order changed an earlier one; the officer's OPEN files citing it. */
export function NoticesPanel({ n }: { n: Notices }) {
  return (
    <section className="notices">
      <h3>Updates for your open files</h3>
      {n.notices.length === 0 && <p className="muted">No new orders affect your open files.</p>}
      {n.notices.map((x, i) => (
        <div key={i} className="flag">
          <div className="flag-head"><strong>{x.new.canonical_id} {CHANGE[x.change] ?? x.change} {x.changed.canonical_id}</strong></div>
          <p>{x.new.subject}</p>
          <p>Open files that rely on {x.changed.canonical_id}: {x.files.map((f) => f.file_no).join(" · ")}</p>
          <p className="src">Applied from the order's own words; review the listed files.</p>
        </div>
      ))}
    </section>
  );
}

/** Receipt inbox (plan §11.2 'Receipt'): the receipts of the officer's section or scope. */
export function ReceiptInbox({ api, open }: { api: Api; open: (computerNo: string) => void }) {
  const [rows, setRows] = useState<ReceiptRow[] | null>(null);
  const [notices, setNotices] = useState<Notices | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.receipts().then((r) => setRows(r.receipts)).catch((e: Error) => setError(e.message));
    api.notices().then(setNotices).catch(() => setNotices(null));
  }, [api]);
  if (error) return <p className="error page">{error}</p>;
  if (!rows) return <p className="muted page">Loading receipts…</p>;
  return (
    <main className="page">
      {notices && <NoticesPanel n={notices} />}
      <h2>Receipt inbox</h2>
      <table className="grid">
        <thead><tr><th>Comp. No.</th><th>Receipt No.</th><th>Diary date</th><th>From</th><th>Letter</th><th>Subject</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.computer_no} className="clickable" onClick={() => open(r.computer_no)}>
              <td>{r.computer_no}</td><td>{r.receipt_no}</td><td>{r.diary_date}</td><td>{r.sender}</td>
              <td>{r.letter_ref ?? ""}{r.letter_pending ? " (letter not yet arrived)" : ""}</td><td>{r.subject}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <p className="muted">No receipts.</p>}
    </main>
  );
}

/** Receipt details with C2-24 Assist (touchpoints 2 and 3). */
export function ReceiptView({ api, computerNo }: { api: Api; computerNo: string }) {
  const [row, setRow] = useState<ReceiptRow | null>(null);
  const [review, setReview] = useState<ReceiptReview | null>(null);
  const [pre, setPre] = useState<Diarise | null>(null);
  const [asOf, setAsOf] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.receipt(computerNo).then((r) => setRow(r.receipt)).catch((e: Error) => setError(e.message));
  }, [api, computerNo]);
  const [arrived, setArrived] = useState<Notices | null>(null);
  const arrive = () => {
    setBusy(true); setError(null);
    api.letterArrives(computerNo)
      .then(() => api.receipt(computerNo)).then((r) => setRow(r.receipt))
      .then(() => api.notices()).then(setArrived)
      .catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  const assist = () => {
    setBusy(true); setError(null);
    api.receiptAssist(computerNo, asOf || undefined).then(setReview)
      .catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  if (error && !row) return <p className="error page">{error}</p>;
  if (!row) return <p className="muted page">Opening receipt…</p>;
  return (
    <div className="panes receipt">
      <section className="corr">
        <h3>Receipt {row.receipt_no}</h3>
        <table className="grid kv">
          <tbody>
            <tr><th>Computer No.</th><td>{row.computer_no}</td></tr>
            <tr><th>Diary date</th><td>{row.diary_date}</td></tr>
            <tr><th>From</th><td>{row.sender}</td></tr>
            <tr><th>Letter</th><td>{row.letter_ref ?? "—"} {row.letter_date ? `dated ${row.letter_date}` : ""}</td></tr>
            <tr><th>Category</th><td>{row.main_category}</td></tr>
            <tr><th>Subject</th><td>{row.subject}</td></tr>
            <tr><th>Section</th><td>{row.dealing_section}</td></tr>
          </tbody>
        </table>
        <div className="actions">
          <button disabled title="Put in a file — the officer decides; not simulated in this slice">Put in a file</button>
          {row.letter_pending && <button className="primary" disabled={busy} onClick={arrive}>Letter arrives (sandbox replay)</button>}
        </div>
        {arrived && <NoticesPanel n={arrived} />}
      </section>
      <aside className="assist">
        <h3>✦ C2-24 Assist — this receipt</h3>
        <div className="row">
          <label className="muted" htmlFor="asof">As of</label>
          <input id="asof" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} title="Sandbox replay; leave empty for today" />
          <button className="primary" disabled={busy} onClick={assist}>Summarise &amp; check</button>
          <button disabled={busy} onClick={() => { setBusy(true); setError(null); api.diarise(computerNo).then(setPre).catch((e: Error) => setError(e.message)).finally(() => setBusy(false)); }}>Pre-fill diary details</button>
        </div>
        {pre && <PrefillCard d={pre} entry={row} />}
        {error && <p className="error">{error}</p>}
        {review && <ReceiptAssistCard r={review} />}
        <p className="footnote">Drafts only. The officer decides where the receipt goes.</p>
      </aside>
    </div>
  );
}

export function ReceiptAssistCard({ r }: { r: ReceiptReview }) {
  if (!r.document) return <p className="card">{r.message}</p>;
  return (
    <section>
      <div className="card">
        {r.summary.map((line, i) => <p key={i}>{line}</p>)}
        <p className="src">Source: {r.document.canonical_id} · as of {r.as_of}</p>
      </div>
      {r.flags.map((f, i) => (
        <div key={i} className="flag">
          <div className="flag-head">
            <strong>{f.type} · {FLAG_NAMES[f.type]} — {f.about}</strong>
            <span className={f.certain ? "badge" : "badge soft"}>{f.certain ? "from records" : "uncertain"}</span>
          </div>
          <p>{f.explanation}</p>
        </div>
      ))}
      {r.flags.length === 0 && <p className="card">No validity flag as of {r.as_of}.</p>}
      {r.status_unconfirmed.length > 0 && (
        <p className="card">Status not confirmed from your records: {r.status_unconfirmed.join(" · ")}</p>
      )}
      <div className="card">
        <p><strong>Put in a file</strong></p>
        {r.put_in.suggestion === "existing_file" && <p>Same subject: {r.put_in.files.join(" · ")}</p>}
        {r.put_in.suggestion === "new_file" && <p>No existing file has the same subject — open a new file.</p>}
        {r.put_in.related_files.length > 0 && (
          <p className="muted">Related (for reference only, not the file to put this in): {r.put_in.related_files.join(" · ")}</p>
        )}
      </div>
    </section>
  );
}

const FIELDS: [keyof Pick<DiaryPrefill, "letter_ref" | "letter_date" | "sender" | "main_category" | "subject">, string][] = [
  ["letter_ref", "Letter ref."], ["letter_date", "Letter date"], ["sender", "From"], ["main_category", "Category"], ["subject", "Subject"],
];
const norm = (v: string | null | undefined) => (v ?? "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

/** Touchpoint 1 — diary fields read from the letter itself, for the clerk to verify. Each value
 *  shows the line it was read from; a field the letter does not give stays empty. */
export function PrefillCard({ d, entry }: { d: Diarise; entry?: ReceiptRow | null }) {
  if (!d.prefill) return <p className="muted">{d.message}</p>;
  const p = d.prefill;
  return (
    <section className="prefill">
      <h4>Diary details read from the letter</h4>
      {p.from_ocr && <p className="pill warn">Read from a scan (OCR, not yet reviewed{p.ocr_confidence != null ? `, lowest page confidence ${p.ocr_confidence.toFixed(2)}` : ""}) — check every field</p>}
      <table className="grid kv">
        <tbody>
          {FIELDS.map(([k, label]) => {
            const f = p[k];
            const diarised = entry ? (entry as unknown as Record<string, string | null>)[k] : undefined;
            return (
              <tr key={k}>
                <th>{label}</th>
                <td>
                  {f.value ?? <span className="muted">not in the letter — fill in</span>}
                  {f.read_from && <div className="sub">from: “{f.read_from}”</div>}
                  {diarised !== undefined && f.value && (
                    <div className="sub">{norm(diarised) === norm(f.value) ? "✓ same as the diary entry" : `diary entry: ${diarised ?? "—"}`}</div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="footnote">Pre-fill only: the clerk verifies and diarises. Nothing is saved by the assistant.</p>
    </section>
  );
}

