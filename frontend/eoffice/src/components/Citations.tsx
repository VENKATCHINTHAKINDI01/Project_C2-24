import { useEffect, useState } from "react";
import { fmtDate } from "../format";
import type { Api } from "../api";
import type { DocumentInfo, Highlight, HighlightState } from "../types";

/** What each highlight colour means (ADR-0015). Advisory: conflicts are prompts to review. */
export const STATE_LABEL: Record<HighlightState, string> = {
  conflict: "Potential conflict",
  review: "Check — your records may not show everything",
  unconfirmed: "Status not confirmed from your records",
  not_found: "Not found in the records available to you",
  ok: "Cited — in force on your records",
  file: "Another e-File",
};

/** ADR-0016: the same guidance whether the order is hidden or does not exist. */
// Same words as backend app/auth/messages.py (ADR-0016, ADR-0019): one answer for a cited order
// C2-24 does not hold and one the officer may not see.
export const NOT_FOUND_GUIDE =
  "It may not be in C2-24's collection yet, or you may need access. If you need it for your work, please request access or approval from the competent authority through e-Office (your section / controlling officer).";

function tip(h: Highlight, canOpenFile: boolean): string {
  const lines = [STATE_LABEL[h.state], ...h.flags.map((f) => `${f.type}: ${f.explanation}`)];
  if (h.canonical_id) lines.push(`Click to open ${h.canonical_id}`);
  else if (h.state === "not_found") lines.push(NOT_FOUND_GUIDE);
  else if (h.kind === "efile") lines.push(canOpenFile ? "Click to open this file" : "Not among the files you can open");
  return lines.join("\n");
}

/** Note text with its citations marked (links, not buttons, so a citation wraps like text). Only orders the officer may open carry a link; the
 *  text itself is shown exactly as written. Overlapping or out-of-range spans are skipped. */
export function HighlightedText({
  text, highlights, onOpenDoc, onOpenFile, fileNos,
}: {
  text: string; highlights: Highlight[]; onOpenDoc: (canonicalId: string) => void;
  onOpenFile: (fileNo: string) => void; fileNos: ReadonlySet<string>;
}) {
  const [notice, setNotice] = useState<string | null>(null); // ADR-0019: clicked citation not available
  const parts: React.ReactNode[] = [];
  let at = 0;
  for (const [i, h] of [...highlights].sort((a, b) => a.start - b.start).entries()) {
    if (h.start < at || h.end > text.length || h.end <= h.start) continue;
    if (h.start > at) parts.push(text.slice(at, h.start));
    const words = text.slice(h.start, h.end);
    const canOpenFile = h.kind === "efile" && h.file_no !== null && fileNos.has(h.file_no);
    const cls = `cite ${h.state}`;
    const id = h.canonical_id;
    const fileNo = h.file_no;
    parts.push(
      id ? (
        <a key={i} href="#" role="button" className={`${cls} open`} title={tip(h, false)} onClick={(e) => { e.preventDefault(); onOpenDoc(id); }}>{words}</a>
      ) : canOpenFile && fileNo ? (
        <a key={i} href="#" role="button" className={`${cls} open`} title={tip(h, true)} onClick={(e) => { e.preventDefault(); onOpenFile(fileNo); }}>{words}</a>
      ) : h.state === "not_found" ? (
        <a key={i} href="#" role="button" className={cls} title={tip(h, false)} onClick={(e) => { e.preventDefault(); setNotice(words); }}>{words}</a>
      ) : (
        <mark key={i} className={cls} title={tip(h, false)}>{words}</mark>
      ),
    );
    at = h.end;
  }
  if (at < text.length) parts.push(text.slice(at));
  return (
    <>
      <pre>{parts}</pre>
      {notice && (
        <div className="cite-notice" role="alert">
          <strong>{notice.replace(/\s+/g, " ")}</strong>: {STATE_LABEL.not_found}. {NOT_FOUND_GUIDE}{" "}
          <button type="button" onClick={() => setNotice(null)}>Close</button>
        </div>
      )}
    </>
  );
}

export function CitationLegend() {
  const shown: HighlightState[] = ["conflict", "review", "unconfirmed", "not_found", "ok"];
  return (
    <p className="legend">
      {shown.map((s) => <mark key={s} className={`cite ${s}`}>{STATE_LABEL[s]}</mark>)}
      <span className="muted"> Click an underlined citation to open the order; a citation not found says why.</span>
    </p>
  );
}

/** Preview / download of a stored source file (ADR-0014). Access is checked by the server on
 *  every request; a document the officer may not see answers like one that does not exist. */
export function DocumentViewer({ api, canonicalId, onClose }: { api: Api; canonicalId: string; onClose: () => void }) {
  const [info, setInfo] = useState<DocumentInfo | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    let made: string | null = null;
    setInfo(null); setUrl(null); setError(null);
    api.documentInfo(canonicalId)
      .then(async (i) => {
        if (!live) return;
        setInfo(i);
        if (i.previewable) {
          const b = await api.documentFile(canonicalId, "preview");
          if (!live) return;
          made = URL.createObjectURL(b);
          setUrl(made);
        }
      })
      .catch((e: Error) => { if (live) setError(e.message); });
    return () => { live = false; if (made) URL.revokeObjectURL(made); };
  }, [api, canonicalId]);

  const download = () => {
    if (!info) return;
    api.documentFile(canonicalId, "download").then((b) => {
      const u = URL.createObjectURL(b);
      const a = document.createElement("a");
      a.href = u; a.download = info.filename; a.click();
      setTimeout(() => URL.revokeObjectURL(u), 1000);
    }).catch((e: Error) => setError(e.message));
  };

  return (
    <div className="viewer" role="dialog" aria-label={`Document ${canonicalId}`}>
      <div className="viewer-head">
        <div>
          <strong>{info?.canonical_id ?? canonicalId}</strong>
          {info && <span className="muted">, {info.doc_type}{info.issue_date ? `, ${fmtDate(info.issue_date)}` : ""}</span>}
          {info && <p className="muted">{info.subject}</p>}
          {info && <RecordStatus info={info} />}
        </div>
        <div className="actions">
          <button onClick={download} disabled={!info}>Download</button>
          <button onClick={onClose} aria-label="Close preview">Close</button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {!error && !info && <p className="muted">Opening…</p>}
      {info && !info.previewable && <p className="muted">This file type can't be shown here. Download it to open.</p>}
      {info && info.previewable && !url && <p className="muted">Loading preview…</p>}
      {url && info?.media_type === "application/pdf" && <iframe title={info.filename} src={url} />}
      {url && info?.media_type.startsWith("image/") && <img alt={info.filename} src={url} />}
      {info && <p className="footnote">Stored copy {info.version.split(":")[1]} — the exact file the citation was read from. Sandbox: synthetic corpus.</p>}
    </div>
  );
}

const STANDING_LINE: Record<string, string> = {
  in_force: "In force", superseded: "Superseded", repealed: "Repealed", expired: "No longer in force (expired)",
  not_yet_in_force: "Not yet in force", unconfirmed: "Status not confirmed from your records",
};
const ENTERED: Record<string, string> = {
  file_created: "file opened", attachment_added: "attached", note_confirmed: "note confirmed",
  draft_dispatched: "order issued", file_closed: "file closed", order_received: "order received",
  receipt_diarised: "receipt diarised", loaded: "loaded",
};

/** ADR-0045: where the record stands today and how it entered the records (versions kept). */
export function RecordStatus({ info }: { info: DocumentInfo }) {
  const line = info.standing ? STANDING_LINE[info.standing] : undefined;
  const history = info.history ?? [];
  if (!line && history.length < 2) return null;
  return (
    <p className="record-status small">
      {line && <strong className={info.standing === "in_force" ? "ok" : "warn"}>{line}</strong>}
      {info.use_instead && <> — use {info.use_instead}</>}
      {history.length > 1 && (
        <span className="muted"> · {history.length} versions: {history.map((h) => `${ENTERED[h.event] ?? h.event} ${fmtDate(h.received_at.slice(0, 10))}`).join(", ")}</span>
      )}
    </p>
  );
}

