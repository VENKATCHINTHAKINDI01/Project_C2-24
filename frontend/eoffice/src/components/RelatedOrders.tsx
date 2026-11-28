import { useCallback, useEffect, useState } from "react";
import type { Api, LinkRef } from "../api";
import type { OrderLink, OrderLinks } from "../types";
import { fmtDateTime } from "../format";

/** ADR-0074: the orders this record replaces, amends or clarifies, and those that do so to it.
 *  The AI finds and explains the link; it never calls an inferred link confirmed. Useful / Not right
 *  are evidence; only an authorised officer's "Confirm this link" (with the order's own sentence)
 *  or the order's own words make a link confirmed. */

const VERB: Record<OrderLink["kind"], [string, string]> = {
  SUPERSEDES: ["replaces", "replace"], AMENDS: ["amends", "amend"], REPEALS: ["repeals", "repeal"], CLARIFIES: ["clarifies", "clarify"],
};

/** "AP-ESE01-GOMS-29-2021" → "G.O.Ms.No.29/2021"; other IDs as they are. */
export function orderName(cid: string): string {
  const m = /^AP-[A-Z0-9]+-(GOMS|GORT)-(\d+)-(\d{4})$/.exec(cid);
  if (!m) return cid;
  return `${m[1] === "GOMS" ? "G.O.Ms" : "G.O.Rt"}.No.${m[2]}/${m[3]}`;
}

/** The line shown for a link: what the system found, never more than the records establish. */
export function linkLine(l: OrderLink): string {
  const [verb, base] = VERB[l.kind];
  const newer = l.this_is === "newer" ? "This order" : orderName(l.other.canonical_id);
  const older = l.this_is === "older" ? "this order" : orderName(l.other.canonical_id);
  switch (l.state) {
    case "validated":
      return l.stated_in_text && !l.decided_post
        ? `${newer} ${verb} ${older} (stated in the order).`
        : `${newer} ${verb} ${older} (confirmed by the ${l.decided_post}${l.decided_at ? `, ${fmtDateTime(l.decided_at)}` : ""}).`;
    case "supported_by_use":
      return `${newer} appears to ${base} ${older}; officers have cited it this way in their work (${l.officers} officers). Please review before relying on it.`;
    case "suggested":
      return `${newer} appears to ${base} ${older}. Please review before relying on it.`;
    case "rejected":
      return `${newer} does not ${base} ${older} (decided by the ${l.decided_post ?? "officer"}).`;
    default:
      return `Possibly related: ${orderName(l.other.canonical_id)}. Please review.`;
  }
}

const ref = (l: OrderLink): LinkRef => ({ source: l.source, kind: l.kind, target: l.target });

function LinkRow({ api, l, onChanged }: { api: Api; l: OrderLink; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deciding, setDeciding] = useState<null | "validate" | "reject" | "request_evidence">(null);
  const [reason, setReason] = useState("");
  const act = (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true); setError(null);
    fn().then(() => { setDone(msg); setDeciding(null); setReason(""); onChanged(); })
      .catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  const byText = l.stated_in_text && !l.decided_post;
  return (
    <li className={`olink ${l.state}`}>
      <p className="olink-line">{linkLine(l)}</p>
      <p className="muted small olink-subject">{orderName(l.other.canonical_id)}: {l.other.subject}</p>
      {l.wording && !byText && <blockquote className="olink-quote">“{l.wording}”<span className="muted small"> — from {orderName(l.source)}</span></blockquote>}
      {l.contested && <p className="warn-text small">Officers have since flagged this link. Please review.</p>}
      {l.evidence_requested && <p className="muted small">More evidence has been asked for.</p>}
      {done && <p className="ok-text small">{done}</p>}
      {error && <p className="error small">{error}</p>}
      {!byText && (l.can_flag || l.can_validate) && !deciding && (
        <div className="olink-actions">
          {l.can_flag && <>
            <button type="button" className="chip" disabled={busy} onClick={() => act(() => api.linkSignal(ref(l), "useful"), "Thank you. Noted as useful.")}>Useful</button>
            <button type="button" className="chip" disabled={busy} onClick={() => act(() => api.linkSignal(ref(l), "not_right"), "Thank you. Noted as not right.")}>Not right</button>
          </>}
          {l.can_validate && <>
            <button type="button" className="chip" disabled={busy || !l.wording} title={l.wording ? "Confirm with the sentence shown" : "No sentence of the newer order states this link"}
              onClick={() => setDeciding("validate")}>Confirm this link</button>
            <button type="button" className="chip" disabled={busy} onClick={() => setDeciding("reject")}>Not a valid link</button>
            <button type="button" className="chip" disabled={busy} onClick={() => setDeciding("request_evidence")}>Ask for more evidence</button>
          </>}
        </div>
      )}
      {deciding && (
        <form className="olink-decide" onSubmit={(e) => { e.preventDefault(); act(() => api.linkDecision(ref(l), deciding, reason.trim(), deciding === "validate" ? l.wording : null), "Recorded with your name and post."); }}>
          <label className="small">{deciding === "validate" ? "Why the sentence above establishes this link" : deciding === "reject" ? "Why this link is not valid" : "What evidence is needed"}
            <input value={reason} minLength={5} maxLength={500} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div className="actions">
            <button type="button" onClick={() => setDeciding(null)}>Cancel</button>
            <button type="submit" className="primary" disabled={busy || reason.trim().length < 5}>
              {deciding === "validate" ? "Confirm this link" : deciding === "reject" ? "Record as not valid" : "Ask for evidence"}
            </button>
          </div>
        </form>
      )}
    </li>
  );
}

export function RelatedOrders({ api, canonicalId }: { api: Api; canonicalId: string }) {
  const [data, setData] = useState<OrderLinks | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api.orderLinks(canonicalId).then(setData).catch((e: Error) => setError(e.message));
  }, [api, canonicalId]);
  useEffect(load, [load]);
  if (error) return <p className="muted small">{error}</p>;
  if (!data) return <p className="muted small">Loading related orders…</p>;
  const shown = data.links.filter((l) => l.state !== "rejected" || l.can_validate);
  if (shown.length === 0) return <p className="muted small">No related orders found.</p>;
  return (
    <ul className="olinks" aria-label="Related orders">
      {shown.map((l) => <LinkRow key={`${l.source}|${l.kind}|${l.target}`} api={api} l={l} onChanged={load} />)}
    </ul>
  );
}
