import { useState } from "react";
import type { Api } from "../api";
import type { Handover } from "../types";

const d = (iso: string | null | undefined) => (iso ? iso.slice(0, 10).split("-").reverse().join("-") : "—");

/** Touchpoint 19 ("Section reassignment"): a cited handover of the officer's section — files in
 *  hand, standing orders, orders no longer in force, recent decisions. Loaded on request; only
 *  files the officer can open and orders they may see are used or counted. */
export function HandoverPanel({ api, open }: { api: Api; open: (computerNo: string) => void }) {
  const [h, setH] = useState<Handover | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = () => {
    setBusy(true); setError(null);
    api.handover().then(setH).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  return (
    <section className="handover" aria-label="Section handover">
      <header>
        <h3>Section handover</h3>
        <button onClick={load} disabled={busy}>{busy ? "Preparing…" : h ? "Refresh" : "Prepare handover summary"}</button>
      </header>
      {!h && !error && <p className="muted">Taking over a section? A summary of its files in hand, the orders it works under and recent decisions — each with its reference.</p>}
      {error && <p className="error">{error}</p>}
      {h && !h.section && <p className="muted">{h.message}</p>}
      {h && h.section && (
        <>
          <p className="card">{h.headline}</p>
          <div className="digest-cols">
            <div>
              <h4>Files in hand <span className="count">{h.in_hand?.length ?? 0}</span></h4>
              <ul>
                {h.in_hand?.slice(0, 12).map((f) => (
                  <li key={f.computer_no}>
                    <button className="linkish" onClick={() => open(f.computer_no)}>{f.file_no}</button>
                    {f.overdue && <span className="pill warn">overdue</span>}
                    {f.sent_back && <span className="pill">sent back</span>}
                    {f.changed_orders > 0 && <span className="pill warn">{f.changed_orders} cited order(s) changed</span>}
                    <div className="sub">{f.subject}</div>
                    <div className="sub">
                      {f.pending_with_post ? `With ${f.pending_with_post}` : "Holder not recorded"}
                      {f.since ? ` since ${d(f.since)}` : ""}{f.days_pending != null ? ` (${f.days_pending} day(s))` : ""}
                      {f.last_direction ? ` · last direction Note #${f.last_direction.note_no}` : ""}
                    </div>
                  </li>
                ))}
              </ul>
              {(h.in_hand?.length ?? 0) > 12 && <p className="muted">and {(h.in_hand?.length ?? 0) - 12} more.</p>}
            </div>
            <div>
              <h4>Orders the section works under</h4>
              {h.standing?.length === 0 && <p className="muted">No cited order you can see.</p>}
              <ul>
                {h.standing?.map((o) => (
                  <li key={o.canonical_id}>
                    <strong>{o.reference}</strong>
                    <span className="pill">{o.status === "in_force" ? "in force" : "status not confirmed for your access"}</span>
                    <span className="muted"> · cited in {o.files.length} file(s)</span>
                    {o.subject && <div className="sub">{o.subject}</div>}
                  </li>
                ))}
              </ul>
              {(h.no_longer_in_force?.length ?? 0) > 0 && (
                <>
                  <h4>Cited but no longer in force — check before relying</h4>
                  <ul>
                    {h.no_longer_in_force?.map((o) => (
                      <li key={o.canonical_id}>
                        <strong>{o.reference}</strong> <span className="pill warn">{o.status}</span>
                        {o.by_reference && <> → {o.by_reference}</>}
                        {o.since && <span className="muted"> · from {d(o.since)}</span>}
                        <span className="muted"> · in {o.files.length} file(s)</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {(h.decisions?.length ?? 0) > 0 && (
                <>
                  <h4>Recent decisions (closed files)</h4>
                  <ul>
                    {h.decisions?.map((x) => (
                      <li key={x.computer_no}>
                        <button className="linkish" onClick={() => open(x.computer_no)}>{x.file_no}</button>
                        <span className="muted"> · Note #{x.decided.note_no}{x.decided.post ? `, ${x.decided.post}` : ""}{x.decided.signed_at ? `, ${d(x.decided.signed_at)}` : ""}</span>
                        <div className="sub">{x.decided.excerpt}</div>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
