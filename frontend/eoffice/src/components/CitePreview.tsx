import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Api } from "../api";
import type { ChatCitation, PassageContext } from "../types";

/** Hover or focus a citation: the cited paragraph, the quoted words marked, without leaving the
 *  file (ADR-0034). Fetched once per citation and quote; the record is checked on the server like
 *  any other — what the officer may not see never arrives. */
const cache = new Map<string, Promise<PassageContext | null>>();

function load(api: Api, cid: string, quote: string): Promise<PassageContext | null> {
  const key = `${cid}\u001f${quote}`;
  let p = cache.get(key);
  if (!p) {
    p = api.docContext(cid, quote).catch(() => null);
    cache.set(key, p);
  }
  return p;
}

export function CitePreview({ api, c, quote, children }: {
  api?: Api; c: ChatCitation; quote: string | null; children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [ctx, setCtx] = useState<PassageContext | null | undefined>(undefined);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!open || !api || !quote || quote.length < 3 || ctx !== undefined) return;
    let live = true;
    void load(api, c.canonical_id, quote).then((r) => { if (live) setCtx(r); });
    return () => { live = false; };
  }, [open, api, quote, c.canonical_id, ctx]);

  const show = () => { timer.current = setTimeout(() => setOpen(true), 250); };
  const hide = () => { if (timer.current) clearTimeout(timer.current); setOpen(false); };

  return (
    <span className="cite-wrap" onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}
      onKeyDown={(e) => { if (e.key === "Escape") hide(); }}>
      {children}
      {open && (
        <span className="cite-pop" role="tooltip">
          <strong>{ctx?.reference ?? c.reference ?? c.canonical_id}</strong>
          {c.status && <span className="pill">{c.status}</span>}
          {ctx?.subject && <span className="subj">{ctx.subject}</span>}
          {ctx === undefined && quote && quote.length >= 3 && <span className="muted">Loading the cited paragraph…</span>}
          {ctx?.paragraph ? <Marked text={ctx.paragraph} at={ctx.highlight} /> :
            ctx !== undefined && <span className="muted">The quoted words were not found in the stored text; open the order to read it.</span>}
        </span>
      )}
    </span>
  );
}

function Marked({ text, at }: { text: string; at: [number, number] | null }) {
  if (!at) return <span className="para">{text}</span>;
  const [s, e] = at;
  return <span className="para">{text.slice(0, s)}<mark>{text.slice(s, e)}</mark>{text.slice(e)}</span>;
}
