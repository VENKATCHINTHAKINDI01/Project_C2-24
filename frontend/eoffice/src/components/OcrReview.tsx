import { useCallback, useEffect, useState } from "react";
import type { Api } from "../api";
import type { OcrReviewDetail, OcrReviewItem, OcrReviewResult } from "../types";

const pct = (c: number | null) => (c === null ? "—" : `${Math.round(c * 100)}%`);

/** Human review of OCR'd scans (plan §4.2). The officer checks the text against the scan, then
 *  confirms it, or corrects and confirms it, or rejects it for a re-scan. Nothing OCR'd is
 *  indexed until this happens. The queue lists only scans this officer may open. */
export function OcrReview({ api }: { api: Api }) {
  const [items, setItems] = useState<OcrReviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [last, setLast] = useState<{ file: string; r: OcrReviewResult } | null>(null);

  const load = useCallback(() => {
    api.ocrQueue().then((q) => setItems(q.items)).catch((e: Error) => setError(e.message));
  }, [api]);
  useEffect(load, [load]);

  if (error) return <p className="error page">{error}</p>;
  if (!items) return <p className="muted page">Loading the review queue…</p>;
  return (
    <main className="page review">
      <h2>OCR review</h2>
      <p className="muted">
        Scanned pages read by Document AI wait here. Check the text against the scan, correct it if needed, and confirm.
        Nothing is used as evidence until you do.
      </p>
      {last && <ResultNote file={last.file} r={last.r} />}
      {items.length === 0 && <p className="muted">No scans are waiting for your review.</p>}
      <div className="review-grid">
        <ul className="review-list">
          {items.map((i) => (
            <li key={i.item_id}>
              <button className={open === i.item_id ? "active" : ""} onClick={() => setOpen(i.item_id)}>
                <strong>{i.filename}</strong>
                <span className="muted">
                  {i.section} · {i.classification} · {i.pages.length} page{i.pages.length === 1 ? "" : "s"} · lowest confidence{" "}
                  {pct(Math.min(...i.pages.map((p) => p.confidence ?? 0)))}
                </span>
              </button>
            </li>
          ))}
        </ul>
        {open && (
          <ReviewItem
            key={open}
            api={api}
            itemId={open}
            onDone={(file, r) => { setLast({ file, r }); setOpen(null); load(); }}
          />
        )}
      </div>
    </main>
  );
}

function ResultNote({ file, r }: { file: string; r: OcrReviewResult }) {
  if (r.status === "indexed")
    return <p className="flag ok-note">{file}: confirmed{r.corrected ? " with your corrections" : ""} and indexed as <strong>{r.canonical_id}</strong>.</p>;
  if (r.status === "rejected") return <p className="flag">{file}: rejected. The file stays out of the index until it is re-scanned.</p>;
  return (
    <div className="flag">
      <p>{file}: your confirmation is recorded, but the file is still held:</p>
      <ul>{(r.still_held_for ?? []).map((h, i) => <li key={i}>{h.kind.replace(/_/g, " ")}: {h.reason}</li>)}</ul>
    </div>
  );
}

function ReviewItem({ api, itemId, onDone }: { api: Api; itemId: string; onDone: (file: string, r: OcrReviewResult) => void }) {
  const [d, setD] = useState<OcrReviewDetail | null>(null);
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const [scan, setScan] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    let made: string | null = null;
    api.ocrItem(itemId)
      .then(async (x) => {
        if (!live) return;
        setD(x); setText(x.draft_text);
        if (x.previewable) {
          const b = await api.ocrScan(itemId);
          if (!live) return;
          made = URL.createObjectURL(b); setScan(made);
        }
      })
      .catch((e: Error) => { if (live) setError(e.message); });
    return () => { live = false; if (made) URL.revokeObjectURL(made); };
  }, [api, itemId]);

  if (error) return <p className="error">{error}</p>;
  if (!d) return <p className="muted">Opening…</p>;
  const edited = text !== d.draft_text;
  const canSend = reason.trim().length >= 3 && !busy;
  const act = (confirm: boolean) => {
    setBusy(true); setError(null);
    (confirm ? api.ocrConfirm(itemId, reason.trim(), edited ? text : null) : api.ocrReject(itemId, reason.trim()))
      .then((r) => onDone(d.filename, r))
      .catch((e: Error) => { setError(e.message); setBusy(false); });
  };
  return (
    <section className="review-item">
      <div className="review-scan">
        {scan && d.media_type === "application/pdf" && <iframe title={`Scan ${d.filename}`} src={scan} />}
        {scan && d.media_type.startsWith("image/") && <img alt={`Scan ${d.filename}`} src={scan} />}
        {!d.previewable && <p className="muted">This file type can't be shown here.</p>}
      </div>
      <div className="review-text">
        <p className="muted">
          {d.engine ?? "no OCR"} · {d.pages.map((p) => `page ${p.page}: ${pct(p.confidence)}${p.languages.length ? ` (${p.languages.join(", ")})` : ""}`).join(" · ")}
        </p>
        {!d.has_draft && <p className="error">No OCR text for this scan ({d.reason}). Type the text from the scan to confirm it, or reject it.</p>}
        <label>
          Text as it will be indexed{edited && <span className="tag"> edited</span>}
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={22} spellCheck={false} />
        </label>
        <label>
          Reason (recorded with your decision)
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. checked every line against the scan" />
        </label>
        <div className="actions">
          <button className="primary" disabled={!canSend || (!d.has_draft && !edited)} onClick={() => act(true)}>
            {edited ? "Confirm corrected text" : "Confirm OCR text"}
          </button>
          <button disabled={!canSend} onClick={() => act(false)}>Reject: needs re-scan</button>
          {edited && <button className="link" onClick={() => setText(d.draft_text)}>Undo my edits</button>}
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    </section>
  );
}
