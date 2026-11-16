import { useEffect, useState } from "react";
import type { Api } from "../api";
import type { Digest } from "../types";

/** "This week for you" (ADR-0034): files waiting with the officer, and orders cited in their open
 *  files that are no longer in force — new ones first. Only files they can open now. */
export function DigestPanel({ api, open }: { api: Api; open: (computerNo: string) => void }) {
  const [d, setD] = useState<Digest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(7);
  useEffect(() => {
    setD(null);
    api.digest(days).then(setD).catch((e: Error) => setError(e.message));
  }, [api, days]);
  if (error) return null; // the digest is a help: the file list still shows
  if (!d) return <p className="muted">Preparing your digest…</p>;
  const fresh = d.changed_orders.filter((c) => c.new);
  const older = d.changed_orders.filter((c) => !c.new);
  const byOrder = (cs: typeof older) => {
    const m = new Map<string, typeof older>();
    cs.forEach((c) => m.set(c.cited, [...(m.get(c.cited) ?? []), c]));
    return [...m.values()];
  };
  return (
    <section className="digest" aria-label="Your digest">
      <header>
        <h3>For you, as of {d.as_of}</h3>
        <label>Changes in the last{" "}
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 14, 30, 90].map((n) => <option key={n} value={n}>{n} days</option>)}
          </select>
        </label>
      </header>
      <div className="digest-cols">
        <div>
          <h4>Waiting with you <span className="count">{d.waiting.length}</span></h4>
          {d.waiting.length === 0 && <p className="muted">No file is waiting with you.</p>}
          <ul>
            {d.waiting.slice(0, 8).map((w) => (
              <li key={w.computer_no}>
                <button className="linkish" onClick={() => open(w.computer_no)}>{w.file_no}</button>
                {w.overdue && <span className="pill warn">overdue</span>}
                {w.sent_back && <span className="pill">sent back</span>}
                {w.priority !== "normal" && <span className="pill">{w.priority}</span>}
                <span className="muted"> {w.days_waiting != null ? `${w.days_waiting} day(s)` : ""}</span>
                <div className="sub">{w.subject}</div>
              </li>
            ))}
          </ul>
          {d.waiting.length > 8 && <p className="muted">and {d.waiting.length - 8} more in the file list.</p>}
        </div>
        <div>
          <h4>Orders cited in your files that changed <span className="count">{fresh.length} new</span></h4>
          {fresh.length === 0 && <p className="muted">No cited order changed in the last {d.window_days} days.</p>}
          <ul>
            {byOrder(fresh).map((cs) => <Change key={cs[0].cited} cs={cs} open={open} isNew />)}
          </ul>
          {older.length > 0 && (
            <details>
              <summary>{byOrder(older).length} older change(s) still cited in your open files</summary>
              <ul>{byOrder(older).map((cs) => <Change key={cs[0].cited} cs={cs} open={open} />)}</ul>
            </details>
          )}
        </div>
      </div>
    </section>
  );
}

function Change({ cs, open, isNew = false }: {
  cs: Digest["changed_orders"]; open: (computerNo: string) => void; isNew?: boolean;
}) {
  const c = cs[0];
  return (
    <li>
      {isNew && <span className="pill new">new</span>}
      <strong>{c.reference}</strong> is {c.status}
      {c.by_reference ? <> by {c.by_reference}</> : null}
      {c.since ? <> from {c.since}</> : null}.
      <div className="sub">Cited in{" "}
        {cs.map((x, i) => (
          <span key={x.computer_no}>{i > 0 && ", "}
            <button className="linkish" onClick={() => open(x.computer_no)}>{x.file_no}</button>
          </span>
        ))}
      </div>
    </li>
  );
}
