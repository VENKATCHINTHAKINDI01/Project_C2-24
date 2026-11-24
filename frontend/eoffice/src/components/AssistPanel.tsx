import { useEffect, useState } from "react";
import { BookOpenText, ClipboardList, FileSignature, FolderCheck, GitCompareArrows, Link2, NotebookPen, Route, ShieldCheck } from "lucide-react";
import { fmtDate } from "../format";
import type { Api } from "../api";
import { FLAG_NAMES, outcomeLabel, yellowNoteFrom } from "../presend";
import { Feedback } from "./Feedback";
import type {
  Brief, DfaPreview, FileSoFar, FirstCut, LinkSuggestions, Movements, NoteReferences, NoteReferenceSuggestion, PresendReport, ReferenceResult,
  SinceDecision, ClosingRemarks,
} from "../types";

/** C2-24 Assist for the open file (plan §11.5 touchpoints 10, 11). Drafts only. */
export function AssistPanel({ api, computerNo, report, onReport, onInserted, onOpenDoc, part = "all" }: {
  api: Api; computerNo: string; report: PresendReport | null;
  /** which tools: all of them, or one tab of the assistant panel (Check / Draft) */
  part?: "all" | "check" | "draft";
  onReport: (r: PresendReport) => void; onInserted: () => void;
  onOpenDoc?: (canonicalId: string) => void; // ADR-0014: open a cited order's stored file
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refText, setRefText] = useState("");
  const [ref, setRef] = useState<ReferenceResult | null>(null);
  const [inserted, setInserted] = useState<string | null>(null);
  const [soFar, setSoFar] = useState<FileSoFar | null>(null);
  const [moves, setMoves] = useState<Movements | null>(null);
  const [since, setSince] = useState<SinceDecision | null>(null);
  const [closing, setClosing] = useState<ClosingRemarks | null>(null);
  const [links, setLinks] = useState<LinkSuggestions | null>(null);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [linked, setLinked] = useState<Record<string, string>>({});
  const [noteAsk, setNoteAsk] = useState("");
  const [noteRefs, setNoteRefs] = useState<NoteReferences | null>(null);
  const [referenced, setReferenced] = useState<Record<string, string>>({});
  const [cut, setCut] = useState<FirstCut | null>(null);
  const [cutBody, setCutBody] = useState("");
  const [cutMade, setCutMade] = useState<string | null>(null);
  const [dfa, setDfa] = useState<DfaPreview | null>(null);
  const [dfaBody, setDfaBody] = useState("");
  const [dfaMade, setDfaMade] = useState<string | null>(null);

  const [working, setWorking] = useState<string | null>(null);
  const checks = part !== "draft";
  // a pre-send report started elsewhere (the toolbar's Send) comes into view in the Check tab
  useEffect(() => {
    if (report && part === "check") requestAnimationFrame(() => document.querySelector(".assist.part-check .presend")?.scrollIntoView({ block: "start", behavior: "smooth" }));
  }, [report, part]);
  const drafts = part !== "check";
  // runs one tool: says what is being prepared, then brings its result into view
  const run = async <T,>(f: () => Promise<T>, then: (x: T) => void, label?: string, show?: string) => {
    setBusy(true); setError(null); setWorking(label ?? null);
    try {
      then(await f());
      if (show) requestAnimationFrame(() => document.querySelector(`.assist ${show}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); setWorking(null); }
  };

  const insert = () => {
    if (!report) return;
    const { body, citations } = yellowNoteFrom(report);
    void run(() => api.insertYellowNote(computerNo, body, citations, report.request_id), (r) => {
      setInserted(r.draft_id); onInserted();
    });
  };

  return (
    <aside className={`assist part-${part}`}>
      {part === "all" && <h3>C2-24 assistant <span className="h3-sub">for this file</span></h3>}
      {working && <p className="busyline" role="status"><span className="dot" />{working}</p>}
      <div className="toolgroups">
        {checks && <div className="toolgroup">
          <h4>Understand the file</h4>
          <div className="tools">
            <button disabled={busy} onClick={() => void run(() => api.fileSoFar(computerNo), setSoFar, "Reading the notes…", ".sofar")}><BookOpenText size={16} aria-hidden="true" /><span>File so far</span></button>
            <button disabled={busy} onClick={() => void run(() => api.movements(computerNo), setMoves, "Reading the movements…", ".moves")}><Route size={16} aria-hidden="true" /><span>Movement summary</span></button>
            <button disabled={busy} onClick={() => void run(() => api.brief(computerNo), setBrief, "Preparing the approval brief…", ".brief")}><ClipboardList size={16} aria-hidden="true" /><span>Approval brief</span></button>
            <button disabled={busy} onClick={() => void run(() => api.sinceDecision(computerNo), setSince, "Checking the orders it relied on…", ".since")}><GitCompareArrows size={16} aria-hidden="true" /><span>Changes since the decision</span></button>
          </div>
        </div>}
        {checks && <div className="toolgroup">
          <h4>Check before sending</h4>
          <div className="tools">
            <button disabled={busy} onClick={() => void run(() => api.presend(computerNo), onReport, "Running the pre-send check…", ".presend")}><ShieldCheck size={16} aria-hidden="true" /><span>Pre-send check</span></button>
            <button disabled={busy} onClick={() => void run(() => api.linkSuggestions(computerNo), setLinks, "Finding related files…", ".links")}><Link2 size={16} aria-hidden="true" /><span>Related files</span></button>
          </div>
        </div>}
        {drafts && <div className="toolgroup">
          <h4>Draft</h4>
          <div className="tools">
            <button disabled={busy} onClick={() => void run(() => api.firstCut(computerNo), (c) => { setCut(c); setCutBody(c.body); setCutMade(null); }, "Writing a first-cut note…", ".dfa")}><NotebookPen size={16} aria-hidden="true" /><span>First-cut note</span></button>
            <button disabled={busy} onClick={() => void run(() => api.dfa(computerNo), (d) => { setDfa(d); setDfaBody(d.body); setDfaMade(null); }, "Preparing the draft…", ".dfa")}><FileSignature size={16} aria-hidden="true" /><span>Draft for approval</span></button>
            <button disabled={busy} onClick={() => void run(() => api.closingRemarks(computerNo), setClosing, "Preparing closing remarks…", ".closing")}><FolderCheck size={16} aria-hidden="true" /><span>Closing remarks</span></button>
          </div>
        </div>}
      </div>

      {checks && <><form className="refbox" onSubmit={(e) => { e.preventDefault(); if (refText.trim()) void run(() => api.reference(refText), setRef); }}>
        <label htmlFor="ref">Local reference — is this order still current?</label>
        <div className="row">
          <input id="ref" value={refText} maxLength={300} placeholder="e.g. G.O.Ms.No.88/2022" onChange={(e) => setRefText(e.target.value)} />
          <button disabled={busy || !refText.trim()}>Check</button>
        </div>
      </form>
      {ref && <ReferenceCard r={ref} />}

      <form className="refbox" onSubmit={(e) => { e.preventDefault(); if (noteAsk.trim()) void run(() => api.noteReference(computerNo, noteAsk), setNoteRefs); }}>
        <label htmlFor="noteref">Refer to an earlier note or page of this file</label>
        <div className="row">
          <input id="noteref" value={noteAsk} maxLength={500} placeholder="e.g. the earlier proposal for an enquiry · Note #1 para 3" onChange={(e) => setNoteAsk(e.target.value)} />
          <button disabled={busy || !noteAsk.trim()}>Find</button>
        </div>
      </form>
      {noteRefs && (
        <NoteReferenceCard
          r={noteRefs}
          done={referenced}
          busy={busy}
          onInsert={(s) =>
            void run(() => api.insertReference(computerNo, s, noteRefs.request_id), (d) => {
              setReferenced((m) => ({ ...m, [s.target_id + ":" + (s.paragraph ?? s.page_from)]: d.draft_id })); onInserted();
            })
          }
        />
      )}</>}

      {error && <p className="error">{error}</p>}
      {checks && brief && <BriefCard b={brief} />}
      {drafts && cut && (
        <FirstCutCard
          c={cut}
          body={cutBody}
          made={cutMade}
          busy={busy}
          onEdit={setCutBody}
          onInsert={() =>
            void run(() => api.insertYellowNote(computerNo, cutBody, cut.citations, cut.request_id), (r) => {
              setCutMade(r.draft_id); onInserted();
            })
          }
        />
      )}
      {drafts && dfa && (
        <DfaCard
          d={dfa}
          body={dfaBody}
          made={dfaMade}
          busy={busy}
          onEdit={setDfaBody}
          onCreate={() =>
            void run(() => api.createDfa(computerNo, dfaBody, dfa.citations, dfa.request_id), (r) => {
              setDfaMade(r.draft_id); onInserted();
            })
          }
        />
      )}
      {checks && soFar && <SoFarCard s={soFar} />}
      {checks && moves && <MovementsCard m={moves} />}
      {checks && since && <SinceCard s={since} onOpenDoc={onOpenDoc} />}
      {drafts && closing && <ClosingCard c={closing} api={api} onClosed={onInserted} />}
      {checks && links && (
        <LinkCard
          s={links}
          linked={linked}
          busy={busy}
          onLink={(fileNo, citations) =>
            void run(() => api.suggestLink(computerNo, fileNo, citations, links.request_id), (r) => {
              setLinked((m) => ({ ...m, [fileNo]: r.draft_id })); onInserted();
            })
          }
        />
      )}

      {checks && report && (
        <PresendCard api={api} computerNo={computerNo} report={report} busy={busy} inserted={inserted}
          onInsert={insert} onOpenDoc={onOpenDoc} />
      )}
      <p className="footnote">Drafts only. Nothing is saved, signed or sent without the officer.</p>
    </aside>
  );
}


/** The pre-send check's result (touchpoint 11): flags with their sources; "Insert as Yellow Note"
 *  makes a draft only on the officer's click. Used in the Check tab and in the file chat. */
export function PresendCard({ api, computerNo, report, busy, inserted, onInsert, onOpenDoc }: {
  api: Api; computerNo: string; report: PresendReport; busy: boolean; inserted: string | null;
  onInsert: () => void; onOpenDoc?: (cid: string) => void;
}) {
  return (
    <section className="presend">
      <h4 className={report.outcome === "conflicts_found" ? "warn" : ""}>{outcomeLabel(report)}</h4>
      {report.message && <p className="card">{report.message}</p>}
      {report.flags?.map((f, i) => (
        <div key={i} className="flag" tabIndex={-1} data-flag={i}>
          <div className="flag-head">
            <strong>{f.type} · {FLAG_NAMES[f.type]}</strong>
            <span className={f.certain ? "badge" : "badge soft"}>{f.certain ? "from records" : "uncertain"}</span>
          </div>
          <p>{f.explanation}</p>
          {f.evidence_ids.length > 0 && (
            <p className="src">Sources:{" "}
              {f.evidence_ids.map((e, j) => (
                <span key={e}>{j > 0 && " · "}{onOpenDoc
                  ? <button type="button" className="doclink" onClick={() => onOpenDoc(e)} title={`Open ${e}`}>{e}</button>
                  : e}</span>
              ))}
            </p>
          )}
          <Feedback api={api} choices={[["accepted", "Needs review"], ["dismissed", "Set aside"]]}
            target={{ kind: "conflict_flag", request_id: report.request_id, computer_no: computerNo,
              flag_type: f.type, canonical_id: f.cited.split(" ")[0] }} />
        </div>
      ))}
      {!!report.status_unconfirmed?.length && (
        <p className="card">Status not confirmed from your records: {report.status_unconfirmed.join(" · ")}</p>
      )}
      {!!report.awaiting_review?.length && (
        <p className="card">
          Not found yet — may be among your records awaiting review (e.g. a scan not yet read):{" "}
          {report.awaiting_review.join(" · ")}
        </p>
      )}
      {!!report.fact_gaps?.length && <p className="card">Not stated clearly in the note: {report.fact_gaps.map(factWords).join(", ")}</p>}
      {report.authority_message && <p className="card">{report.authority_message}</p>}
      <Caveats calibrated={report.calibrated} mockRules={report.mock_rules} />
      {!!report.flags?.length && (
        <div className="actions">
          <button className="primary" disabled={busy || inserted !== null} onClick={onInsert}>Insert as Yellow Note</button>
          {inserted && <span className="muted">Draft {inserted} added to the noting panel.</span>}
        </div>
      )}
    </section>
  );
}

const fmtRs = (n: number) => `Rs.${(n / 1e7).toFixed(2)} crore`;

/** Touchpoint 13: approval brief for a senior — built from the file's own records; every item
 *  is something the officer can open. No model-written text. */
export function BriefCard({ b }: { b: Brief }) {
  const p = b.proposal;
  const flags = b.presend?.flags ?? [];
  const waiting = new Set(b.presend?.awaiting_review ?? []);
  return (
    <section className="brief">
      <h4>Approval brief — {b.file_no}</h4>
      <div className="card">
        <p><strong>Proposal:</strong> {p.action ?? "not stated"}
          {p.post_level ? ` · ${p.post_level} post` : ""}
          {p.amount_rupees != null ? ` · ${fmtRs(p.amount_rupees)}` : ""}
          {p.proposed_authority ? ` · approval sought from ${p.proposed_authority}` : ""}
        </p>
        {p.evidence.proposed_authority && <p className="src">“{p.evidence.proposed_authority}”</p>}
        {p.not_stated.length > 0 && <p className="muted">Not stated clearly in the note: {p.not_stated.map(factWords).join(", ")}</p>}
        {b.put_up && <p className="muted">Put up by {b.put_up.post ?? "—"}{b.put_up.signed_at ? ` on ${b.put_up.signed_at.slice(0, 10)}` : ""}</p>}
      </div>
      <div className="card">
        <p><strong>Orders the note relies on</strong></p>
        {b.governing.length === 0 && <p className="muted">The note cites no order.</p>}
        {b.governing.map((g) => (
          <p key={g.cited}>{g.cited}: {g.status ? g.status.replace(/_/g, " ") : g.found ? "status not confirmed" : waiting.has(g.cited) ? "not found yet — may be awaiting review" : "not found"}
            {g.by ? ` by ${g.by}` : ""}{g.message ? <span className="muted"> — {g.message}</span> : null}</p>
        ))}
      </div>
      <div className="card">
        <p><strong>Flags</strong> {flags.length === 0 && <span className="muted">none from the records</span>}</p>
        {flags.map((f, i) => (
          <p key={i}>{f.type} · {FLAG_NAMES[f.type]}{f.certain ? "" : " (uncertain)"} — <span className="muted">{f.cited}</span></p>
        ))}
      </div>
      <div className="card">
        <p><strong>Precedent files</strong></p>
        {b.precedents.length === 0 && <p className="muted">None in your records.</p>}
        {b.precedents.map((x) => (
          <p key={x.file_no}>{x.file_no} <span className="muted">— {x.documents[0]?.subject}</span></p>
        ))}
      </div>
      {b.movement.length > 0 && <p className="muted">Movement so far: {b.movement.join(" → ")}</p>}
    </section>
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
            {n.signed_at && <>, {fmtDate(n.signed_at)}</>}
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

const ddmmyyyy = (iso: string | null) => fmtDate(iso);

/** The rule engine names the facts it needs by field; the officer reads them in words. */
const FACT_WORDS: Record<string, string> = {
  action: "what is proposed", post_level: "the post level", amount: "the amount",
  proposed_authority: "who is proposed to approve it", "note identity/date/department": "the note's number, date or department",
};
const factWords = (f: string) => FACT_WORDS[f] ?? f.replace(/_/g, " ");

/** Touchpoint 12 ("Initiate action"): the remarks at each movement, the note each sender put up,
 *  and where the file is pending — e-Office's own records, nothing inferred. */
export function MovementsCard({ m }: { m: Movements }) {
  return (
    <section className="moves">
      <h4>Movement summary — {m.file_no}</h4>
      <p className={`card${m.overdue ? " warnline" : ""}`}>{m.headline}</p>
      {m.steps.length === 0 && <p className="muted">The file has not moved yet.</p>}
      <ol className="timeline">
        {m.steps.map((s) => (
          <li key={s.seq} className={s.sent_back ? "back" : ""}>
            <div><strong>{s.from_post ?? s.from_user}</strong> → <strong>{s.to_post ?? s.to_user}</strong>
              <span className="muted">, {ddmmyyyy(s.sent_at)}{s.days_held != null ? `, held ${s.days_held} day(s)` : ""}</span>
              {s.sent_back && <span className="pill warn">sent back</span>}
              {s.priority !== "normal" && <span className="pill">{s.priority}</span>}
              {s.due_on && <span className="pill">due {ddmmyyyy(s.due_on)}</span>}
            </div>
            {s.remarks && <div className="remarks">“{s.remarks}”</div>}
            {s.notes.map((n) => (
              <div key={n.note_no} className="sub">Note #{n.note_no}: {n.excerpt || "(no text besides the signature)"}</div>
            ))}
            {s.notes.length === 0 && <div className="sub muted">No note of the sender before this movement is available to you.</div>}
          </li>
        ))}
      </ol>
      {m.last_direction && (
        <p className="muted">Last direction: Note #{m.last_direction.note_no}{m.last_direction.post ? `, ${m.last_direction.post}` : ""} — {m.last_direction.excerpt}</p>
      )}
    </section>
  );
}

/** Touchpoint 16 — suggested closing remarks from the file's own record; the officer edits them
 *  and closes the file (simulated e-Office). Blockers are shown, never hidden. */
export function ClosingCard({ c, api, onClosed }: { c: ClosingRemarks; api: Api; onClosed?: () => void }) {
  const [text, setText] = useState(c.text ?? "");
  const [done, setDone] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const close = () => {
    setErr(null);
    api.closeFile(c.computer_no, text).then(() => { setDone("File closed. Its notes go to the precedent index."); onClosed?.(); })
      .catch((e: Error) => setErr(e.message));
  };
  return (
    <section className="closing">
      <h4>Closing remarks — {c.file_no}</h4>
      {c.blockers.length > 0 && <ul className="blockers">{c.blockers.map((b) => <li key={b}>{b}</li>)}</ul>}
      <textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder="Closing remarks in your words" aria-label="Closing remarks" />
      <div className="actions">
        <button className="primary" disabled={!c.can_close || text.trim().length < 5 || !!done} onClick={close}>Close file</button>
      </div>
      {done && <p className="ok">{done}</p>}
      {err && <p className="error">{err}</p>}
      <p className="footnote">A suggestion: edit it as needed. Closing is your action in e-Office.</p>
    </section>
  );
}

const CHANGE: Record<string, string> = {
  superseded: "superseded by", repealed: "repealed by", expired: "expired", amended: "amended by", clarified: "clarified by",
};

/** Touchpoint 17 ("Reopening a file"): what was decided and what has changed since in the orders
 *  the file relied on — status, amendments, clarifications — within the officer's access. */
export function SinceCard({ s, onOpenDoc }: { s: SinceDecision; onOpenDoc?: (cid: string) => void }) {
  const after = s.changes.filter((c) => c.after_decision !== false);
  const before = s.changes.filter((c) => c.after_decision === false);
  const row = (c: SinceDecision["changes"][number], i: number) => (
    <li key={i}>
      <button className="linkish" onClick={() => onOpenDoc?.(c.cited)}>{c.cited_reference}</button>{" "}
      <span className={`pill${c.change === "amended" || c.change === "clarified" ? "" : " warn"}`}>{CHANGE[c.change] ?? c.change}</span>{" "}
      {c.by && <button className="linkish" onClick={() => onOpenDoc?.(c.by!)}>{c.by_reference ?? c.by}</button>}
      {c.on && <span className="muted"> · from {ddmmyyyy(c.on)}</span>}
      {c.after_decision == null && <span className="muted"> · date unknown</span>}
      {c.by_subject && <div className="sub">{c.by_subject}</div>}
    </li>
  );
  return (
    <section className="since">
      <h4>{s.state === "closed" ? "Since the decision" : "Since the last direction"} — {s.file_no}</h4>
      <p className="card">{s.headline}</p>
      {s.decided && <blockquote className="decided">Note #{s.decided.note_no}{s.decided.post ? ` · ${s.decided.post}` : ""}: {s.decided.excerpt}</blockquote>}
      {after.length > 0 && (<><h5>Changed since</h5><ul>{after.map(row)}</ul></>)}
      {before.length > 0 && (<><h5>{s.state === "closed" ? "Already changed when it was decided" : "Already changed before the last direction"}</h5><ul>{before.map(row)}</ul></>)}
      {s.unchanged.length > 0 && <p className="muted">No change found for {s.unchanged.length} other order(s) it relied on, in the records available to you.</p>}
    </section>
  );
}

/** Touchpoint 9: precedent files to link — only files in the officer's scope; a click records a
 *  suggested-reference DRAFT that the officer confirms in e-Office. */
export function LinkCard({ s, linked, busy, onLink }: {
  s: LinkSuggestions; linked: Record<string, string>; busy: boolean;
  onLink: (fileNo: string, citations: string[]) => void;
}) {
  return (
    <section className="links">
      <h4>Precedent files to link</h4>
      {s.message && <p className="card">{s.message}</p>}
      {s.suggestions.map((l) => (
        <div key={l.file_no} className="card">
          <p><strong>{l.file_no}</strong></p>
          {l.documents.map((d) => <p key={d.canonical_id} className="muted">{d.issue_date ?? ""} · {d.subject}</p>)}
          <div className="actions">
            {linked[l.file_no]
              ? <span className="muted">Suggested link {linked[l.file_no]} added as a draft.</span>
              : <button disabled={busy} onClick={() => onLink(l.file_no, l.documents.map((d) => d.canonical_id))}>Suggest link</button>}
          </div>
        </div>
      ))}
    </section>
  );
}

/** Touchpoint 6: every point quoted from a record the officer may see, with its ID.
 *  The officer writes the note around them; "Insert as Yellow Note" saves a draft only. */
export function FirstCutCard({ c, body, made, busy, onEdit, onInsert }: {
  c: FirstCut; body: string; made: string | null; busy: boolean;
  onEdit: (s: string) => void; onInsert: () => void;
}) {
  const windowLine = (p: FirstCut["precedents"][number]) =>
    p.in_window === null ? "no window in your records to compare"
      : p.in_window ? `inside the window in ${p.windows.join(", ")}` : "outside every relaxation window in your records";
  return (
    <section className="dfa">
      <h4>First-cut note — cited points</h4>
      <div className="card">
        <p><strong>Orders that apply</strong></p>
        <ol>
          {c.orders.map((o) => (
            <li key={o.canonical_id}>
              {o.canonical_id}
              {o.in_place_of.length > 0 && <span className="badge">in place of {o.in_place_of.join(", ")}</span>}
              {!o.status_confirmed && <span className="muted"> · status not confirmed</span>}
            </li>
          ))}
        </ol>
      </div>
      {c.points.length > 0 && (
        <div className="card">
          <p><strong>Points from those orders</strong></p>
          {c.points.map((p) => (
            <div key={p.clause_id} className="clause"><p className="src">{p.topic} · {p.clause_id}</p><p>{p.text}</p></div>
          ))}
        </div>
      )}
      {c.precedents.length > 0 && (
        <div className="card">
          <p><strong>Earlier decisions in similar cases</strong></p>
          {c.precedents.map((p) => (
            <div key={p.source} className="clause">
              <p className="src">{p.file_no} · Note #{p.note_no} · {p.decided_on ? fmtDate(p.decided_on) : "date not recorded"}</p>
              <p>“{p.decision}”</p>
              <p className="muted">{windowLine(p)}</p>
            </div>
          ))}
        </div>
      )}
      {c.flags.length > 0 && (
        <p className="card">Open points: {c.flags.map((f) => `${f.type} · ${FLAG_NAMES[f.type]}`).join("; ")}</p>
      )}
      <label htmlFor="cutbody">Note text (write the note around the cited points; edit before inserting)</label>
      <textarea id="cutbody" rows={14} value={body} onChange={(e) => onEdit(e.target.value)} />
      <div className="actions">
        {made
          ? <span className="muted">Yellow Note {made} added to the noting panel. Not confirmed or sent.</span>
          : <button className="primary" disabled={busy || !body.trim()} onClick={onInsert}>Insert as Yellow Note</button>}
      </div>
    </section>
  );
}

/** Touchpoint 14: what C2-24 can prepare without a model — abstract, "Read the following",
 *  open points. The officer edits; "Create DFA draft" saves a draft only. */
export function DfaCard({ d, body, made, busy, onEdit, onCreate }: {
  d: DfaPreview; body: string; made: string | null; busy: boolean;
  onEdit: (s: string) => void; onCreate: () => void;
}) {
  return (
    <section className="dfa">
      <h4>Draft for approval — {d.file_no}</h4>
      <div className="card">
        <p><strong>Read the following</strong></p>
        {d.read_list.length === 0 && <p className="muted">No order on this subject in your records.</p>}
        <ol>
          {d.read_list.map((i) => (
            <li key={i.canonical_id}>
              {i.canonical_id} <span className="muted">· {i.issue_date ? fmtDate(i.issue_date) : "date not recorded"}</span>
              {i.in_place_of.length > 0 && <span className="badge">in place of {i.in_place_of.join(", ")}</span>}
              {!i.status_confirmed && <span className="muted"> · status not confirmed</span>}
              <p className="muted">{i.subject}</p>
            </li>
          ))}
        </ol>
        {d.left_out.map((x) => <p key={x.cited} className="warn">Not listed: {x.cited} — {x.reason}.</p>)}
      </div>
      {d.flags.length > 0 && (
        <p className="card">Open points travel with the draft: {d.flags.map((f) => `${f.type} · ${FLAG_NAMES[f.type]}`).join("; ")}</p>
      )}
      {d.caveats.map((c) => <p key={c} className="muted">{c}</p>)}
      <label htmlFor="dfabody">Draft text (edit before saving; order paragraphs are yours to write)</label>
      <textarea id="dfabody" rows={14} value={body} onChange={(e) => onEdit(e.target.value)} />
      <div className="actions">
        {made
          ? <span className="muted">DFA draft {made} saved to the file. Not approved, signed or issued.</span>
          : <button disabled={busy || !body.trim()} onClick={onCreate}>Create DFA draft</button>}
      </div>
    </section>
  );
}

/** Touchpoint 7: suggestions only; "Insert reference" creates a suggested-reference draft. */
export function NoteReferenceCard({ r, done, busy, onInsert }: {
  r: NoteReferences; done: Record<string, string>; busy: boolean;
  onInsert: (s: NoteReferenceSuggestion) => void;
}) {
  return (
    <section className="noterefs">
      <h4>References in this file</h4>
      {r.message && <p className="card">{r.message}</p>}
      {r.suggestions.map((s) => {
        const key = s.target_id + ":" + (s.paragraph ?? s.page_from);
        return (
          <div key={key} className="card">
            <p><strong>{s.insert_text}</strong> <span className="muted">· {s.target_id}</span></p>
            <p>{s.text}</p>
            {s.source && <p className="src">Source: {s.source}</p>}
            {s.matched_terms.length > 0 && <p className="muted">Matched words: {s.matched_terms.join(", ")}</p>}
            <div className="actions">
              {done[key]
                ? <span className="muted">Reference {done[key]} added as a draft.</span>
                : <button disabled={busy} onClick={() => onInsert(s)}>Insert reference</button>}
            </div>
          </div>
        );
      })}
      {r.matched_by === "keywords" && <p className="muted">Matched by shared words ({r.matching}) — check it is the right paragraph.</p>}
    </section>
  );
}


export function ReferenceCard({ r }: { r: ReferenceResult }) {
  if (r.choices?.length) return <p className="card">More than one order matches — which one? {r.choices.join(" · ")}</p>;
  if (!r.found) return <p className="card">{r.message}</p>;
  const d = r.documents?.[0];
  return (
    <div className="card">
      {d && <p><strong>{d.canonical_id}</strong> — {d.subject}</p>}
      {r.status && <p>Status: <strong>{r.status.replace(/_/g, " ")}</strong>{r.by ? <> by <strong>{r.by}</strong></> : null}{r.since ? <> from {fmtDate(r.since)}</> : null}</p>}
      {r.current_version && r.current_version !== d?.canonical_id && <p>Current version: <strong>{r.current_version}</strong></p>}
      {r.message && <p className="muted">{r.message}</p>}
      {r.cited_clause && (
        <div className="clause"><p className="src">{r.cited_clause.clause_id}</p><p>{r.cited_clause.text}</p></div>
      )}
      {r.successor_clause && (
        <div className="clause">
          <p className="src">{r.successor_clause.clause_id}{r.successor_is_current ? " · current" : ""}</p>
          <p>{r.successor_clause.text}</p>
        </div>
      )}
      {r.clause_note && <p className="muted">{r.clause_note}</p>}
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
