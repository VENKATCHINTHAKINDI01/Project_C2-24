import { useEffect, useMemo, useRef, useState } from "react";
import type { Api } from "../api";
import { fmtDate, fmtDateTime } from "../format";
import type {
  CloseMatch, DraftFormat, DraftFormats, DraftInputs, DraftRelation, DraftWorkspace, InputName, PreparedDraft, Standing,
} from "../types";
import { DocumentViewer } from "./Citations";

/** Draft workspace (ADR-0044). Choose a format, give the facts and what is proposed, and get a
 *  draft in that format with "Read the following" from your records, the pre-send check on the
 *  draft, and the records closest to it (our hybrid search and graph), each with its standing
 *  and relations, to preview, download and add. Nothing reaches a file until you Save.
 *
 *  Without a file (a new matter) the subject is required, earlier files on the same subject are
 *  offered as Previous References, and Save opens the new e-File first and puts the draft in it. */

const FIELD: Record<InputName, { label: string; rows: number; help?: string }> = {
  subject: { label: "Subject", rows: 2 },
  request: { label: "What the receipt (PUC) asks for, or the background", rows: 3 },
  facts: { label: "Facts verified", rows: 4, help: "Your own words, put in the draft as you write them. A blank line starts a new paragraph." },
  proposal: { label: "What is proposed", rows: 4 },
  signatory: { label: "Signatory (name and post)", rows: 1 },
  addressees: { label: "To (one per line)", rows: 3 },
  copy_to: { label: "Copy to (one per line)", rows: 2 },
};
const PROPOSAL_LABEL: Record<DraftFormat["kind"], string> = {
  note: "What is proposed",
  go: "What Government now order",
  memo: "The clarification or instruction",
  letter: "What is requested",
};
const STANDING: Record<Standing, { text: string; tone: string }> = {
  in_force: { text: "In force", tone: "ok" },
  superseded: { text: "Superseded", tone: "bad" },
  repealed: { text: "Repealed", tone: "bad" },
  expired: { text: "Expired", tone: "bad" },
  not_yet_in_force: { text: "Not yet in force", tone: "warn" },
  unconfirmed: { text: "Status not confirmed", tone: "warn" },
  not_an_order: { text: "Earlier paper", tone: "plain" },
};
const REL: Record<string, [string, string]> = { // [this → other, other → this]
  SUPERSEDES: ["Supersedes", "Superseded by"],
  AMENDS: ["Amends", "Amended by"],
  CLARIFIES: ["Clarifies", "Clarified by"],
  REPEALS: ["Repeals", "Repealed by"],
  REFERENCES: ["Refers to", "Referred to by"],
  CITES: ["Cites", "Cited by"],
};
const WHY_NO_WORDING: Record<string, string> = {
  engine_off: "The model is not configured in this sandbox, so no wording was suggested. Write the paragraphs yourself.",
  engine_down: "The model did not answer (the main model and the fallback were both unavailable). Nothing was guessed.",
  no_sources: "Write the facts or what is proposed first: suggested wording is built only from your own inputs and the orders read.",
  all_removed: "Every suggested line failed the check against its sources and was removed.",
};

export function relationText(r: DraftRelation): string {
  const [out, inn] = REL[r.kind] ?? [r.kind, r.kind];
  return `${r.direction === "out" ? out : inn} ${r.other_label}`;
}

export const MIN_SUBJECT = 10; // as e-Office "Create File" asks (CreateFileIn)

export function DraftStudio({ api, computerNo, initialFormat, back, onSaved, openFile }: {
  api: Api; computerNo?: string; initialFormat?: string; back: () => void; onSaved: () => void;
  openFile?: (computerNo: string) => void;
}) {
  const [formats, setFormats] = useState<DraftFormats | null>(null);
  const [formatId, setFormatId] = useState<string | undefined>(initialFormat);
  const [fileNo, setFileNo] = useState("");
  const [inputs, setInputs] = useState<DraftInputs>({});
  const [suggest, setSuggest] = useState(false);
  const [added, setAdded] = useState<string[]>([]);
  const [dropped, setDropped] = useState<string[]>([]);
  const [prep, setPrep] = useState<PreparedDraft | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);
  const [refs, setRefs] = useState<string[]>([]); // a new matter: files to enter as Previous References
  const [created, setCreated] = useState<{ computerNo: string; fileNo: string } | null>(null);
  const target = computerNo ?? created?.computerNo; // the file the draft goes to, once there is one
  const isNew = computerNo === undefined;
  // Draft recovery (ADR-0046): the server keeps this screen's state as the officer works
  const wsKey = computerNo ?? null; // null: a new matter
  const [ready, setReady] = useState(false); // restore attempted: autosave may start
  const [restoredAt, setRestoredAt] = useState<string | null>(null);
  const [autosave, setAutosave] = useState<string | null>(null);
  const [stored, setStored] = useState(false); // a new matter saved into its file: nothing to recover

  useEffect(() => {
    api.draftFormats().then(setFormats).catch((e: Error) => setError(e.message));
    if (computerNo === undefined) return;
    api.file(computerNo).then((f) => {
      setFileNo(f.file.file_no);
      setInputs((i) => ({ subject: f.file.subject, ...i }));
    }).catch((e: Error) => setError(e.message));
  }, [api, computerNo]);

  const fmt = useMemo(() => formats?.formats.find((f) => f.id === formatId), [formats, formatId]);
  const subjectShort = isNew && (inputs.subject ?? "").trim().length < MIN_SUBJECT;

  /** `keep`: a restore — the records beside the draft are worked out again under the officer's
   *  access today, and the draft keeps the text exactly as they left it. */
  async function prepare(add = added, drop = dropped, keep?: { formatId: string; inputs: DraftInputs; suggest: boolean }) {
    const id = keep?.formatId ?? fmt?.id;
    if (!id) return;
    setBusy(keep ? "Restoring your draft and checking your records again…" : "Preparing the draft and checking your records…");
    setError(null); setSaved(null);
    try {
      const r = await api.prepareDraft({
        computer_no: computerNo ?? null, format_id: id, inputs: keep?.inputs ?? inputs,
        add_references: add, drop_references: drop, suggest: keep ? false : suggest,
      });
      setPrep(r);
      if (!keep) setText(r.draft.text);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  }

  // restore where the officer left off (their own workspace; access re-checked by the server)
  useEffect(() => {
    let live = true;
    api.getWorkspace(wsKey).then(({ workspace: ws, saved_at }) => {
      if (!live) return;
      if (ws && (ws.format_id || ws.text || Object.values(ws.inputs).some((v) => v.trim()))) {
        const fid = ws.format_id ?? initialFormat;
        setFormatId(fid); setInputs(ws.inputs as DraftInputs); setSuggest(ws.suggest);
        setAdded(ws.added); setDropped(ws.dropped); setRefs(ws.previous_references); setText(ws.text);
        setRestoredAt(saved_at);
        if (ws.prepared && fid) void prepare(ws.added, ws.dropped, { formatId: fid, inputs: ws.inputs as DraftInputs, suggest: ws.suggest });
      }
    }).catch(() => { /* nothing to restore, or not available: start fresh */ })
      .finally(() => { if (live) setReady(true); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, wsKey]);

  const snapshot = (): DraftWorkspace => ({
    format_id: formatId ?? null, inputs: inputs as Record<string, string>, suggest, added, dropped,
    previous_references: refs, prepared: prep !== null, text,
  });
  const latest = useRef(snapshot);
  latest.current = snapshot;
  const worth = Boolean(formatId || text.trim() || (inputs.facts ?? "").trim() || (inputs.proposal ?? "").trim() || (isNew && (inputs.subject ?? "").trim()));

  // autosave a moment after each change
  useEffect(() => {
    if (!ready || stored || !worth) return undefined;
    setAutosave("Saving…");
    const t = window.setTimeout(() => {
      api.saveWorkspace(wsKey, latest.current())
        .then((r) => setAutosave(`Saved ${fmtDateTime(r.saved_at)}`))
        .catch(() => setAutosave("Not saved yet — will try again with your next change"));
    }, 1500);
    return () => window.clearTimeout(t);
  }, [api, wsKey, ready, stored, worth, formatId, inputs, suggest, added, dropped, refs, text, prep]);

  // and once more as the page goes away (tab closed, screen locked, power about to go)
  useEffect(() => {
    const leave = () => { if (ready && !stored && worth) api.saveWorkspaceOnLeave(wsKey, latest.current()); };
    const hidden = () => { if (document.visibilityState === "hidden") leave(); };
    window.addEventListener("pagehide", leave);
    document.addEventListener("visibilitychange", hidden);
    return () => { window.removeEventListener("pagehide", leave); document.removeEventListener("visibilitychange", hidden); };
  }, [api, wsKey, ready, stored, worth]);

  async function startOver() {
    try { await api.discardWorkspace(wsKey); } catch { /* the screen is reset either way */ }
    setFormatId(initialFormat); setInputs(isNew ? {} : { subject: inputs.subject }); setSuggest(false);
    setAdded([]); setDropped([]); setRefs([]); setPrep(null); setText(""); setRestoredAt(null); setAutosave(null);
  }
  const addRef = (cid: string) => { const a = [...added.filter((x) => x !== cid), cid]; setAdded(a); setDropped(dropped.filter((x) => x !== cid)); void prepare(a, dropped.filter((x) => x !== cid)); };
  const dropRef = (cid: string) => { const d = [...dropped, cid]; setDropped(d); setAdded(added.filter((x) => x !== cid)); void prepare(added.filter((x) => x !== cid), d); };

  /** The stored file itself, checked by the server like any other request (ADR-0014). */
  async function download(cid: string) {
    try {
      const [info, b] = await Promise.all([api.documentInfo(cid), api.documentFile(cid, "download")]);
      const u = URL.createObjectURL(b);
      const a = document.createElement("a");
      a.href = u; a.download = info.filename; a.click();
      setTimeout(() => URL.revokeObjectURL(u), 1000);
    } catch (e) { setError((e as Error).message); }
  }

  async function save() {
    if (!prep) return;
    setBusy(target ? "Saving the draft to the file…" : "Creating the file and saving the draft…"); setError(null);
    let into = target;
    try {
      if (!into) { // a new matter: the officer's click opens the e-File, then the draft goes in it
        const f = await api.createFile((inputs.subject ?? "").trim(), refs);
        into = f.file.computer_no;
        setCreated({ computerNo: into, fileNo: f.file.file_no });
      }
      const fn = prep.draft.saves_as === "yellow_note" ? api.insertYellowNote : api.createDfa;
      const r = await fn(into, text, prep.draft.citations, prep.request_id);
      const kind = prep.draft.saves_as === "yellow_note" ? "a Yellow Note" : "a DFA draft";
      setSaved(`Saved as ${kind} (${r.draft_id}) on ${into === computerNo ? "the file" : "the new file"}. It stays a draft until you confirm and sign it in e-Office.`);
      // it is on the file now: nothing left to recover (the server clears a file's own workspace)
      if (isNew) { setStored(true); void api.discardWorkspace(null).catch(() => undefined); }
      setRestoredAt(null); setAutosave(null);
      onSaved();
    } catch (e) {
      const msg = (e as Error).message;
      setError(into && into !== computerNo && !created ? `The file was created, but the draft was not saved: ${msg} Save again to put it in that file.` : msg);
    }
    finally { setBusy(null); }
  }

  const groups: [string, DraftFormat[]][] = formats
    ? [["Notes", formats.formats.filter((f) => f.family === "noting")], ["Orders and letters (DFA)", formats.formats.filter((f) => f.family === "outgoing")]]
    : [];
  const gaps = (text.match(/\[[^\]\n]{2,120}\]/g) ?? []).length;

  return (
    <main className="page drafting">
      <div className="draft-head">
        <div>
          <h1>{isNew ? "New draft" : "Draft"}</h1>
          {isNew
            ? <p className="muted">{created ? <>On the new file {created.fileNo} · <button className="link" onClick={() => openFile?.(created.computerNo)}>Open the file</button></> : <>A new matter: no file is needed yet. Saving opens a new e-File with your subject and puts the draft in it.</>} · <button className="link" onClick={back}>Back</button></p>
            : <p className="muted">File {fileNo || computerNo} · <button className="link" onClick={back}>Back to the file</button></p>}
          {autosave && <p className="autosave small muted" role="status">{autosave}</p>}
        </div>
        {formats?.status === "mock" && (
          <p className="mock-note">Formats are taken from orders, memos and notes in the corpus, not from an official template. Confirm them against the Office Manual before real use.</p>
        )}
      </div>
      {restoredAt && (
        <p className="restored" role="status">
          Restored where you left off (saved {fmtDateTime(restoredAt)}). The records beside the draft were checked again just now.
          {" "}<button className="link" onClick={() => void startOver()}>Start over</button>
        </p>
      )}
      {error && <p className="error" role="alert">{error}</p>}

      <div className="draft-grid">
        <section className="draft-formats" aria-label="Formats">
          <h2>1. Choose a format</h2>
          {groups.map(([title, list]) => (
            <div key={title} className="fmt-group">
              <h3>{title}</h3>
              <ul role="radiogroup" aria-label={title}>
                {list.map((f) => (
                  <li key={f.id}>
                    <label className={`fmt${f.id === formatId ? " on" : ""}`}>
                      <input type="radio" name="draft-format" checked={f.id === formatId}
                        onChange={() => { setFormatId(f.id); setPrep(null); setText(""); }} />
                      <strong>{f.title}</strong>
                      <span className="muted">{f.use_when}</span>
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {fmt && (
            <details className="skeleton" open={!prep}>
              <summary>How a {fmt.title.toLowerCase()} is laid out</summary>
              <pre>{fmt.skeleton}</pre>
              <p className="muted">From: {fmt.basis}</p>
            </details>
          )}
        </section>

        <section className="draft-inputs" aria-label="Your inputs">
          <h2>2. Your inputs</h2>
          {!fmt && <p className="muted">Choose a format first. Its fields appear here.</p>}
          {fmt && (
            <form onSubmit={(e) => { e.preventDefault(); void prepare(); }}>
              {fmt.inputs.map((name) => (
                <label key={name} className="field">
                  <span>{name === "proposal" ? PROPOSAL_LABEL[fmt.kind] : FIELD[name].label}</span>
                  <textarea rows={FIELD[name].rows} value={inputs[name] ?? ""} maxLength={name === "subject" ? 500 : 4000}
                    onChange={(e) => setInputs({ ...inputs, [name]: e.target.value })} />
                  {FIELD[name].help && <small className="muted">{FIELD[name].help}</small>}
                  {name === "subject" && isNew && <small className="muted">Required: it becomes the subject of the new file, and the records are searched by it.</small>}
                </label>
              ))}
              <label className="check">
                <input type="checkbox" checked={suggest} onChange={(e) => setSuggest(e.target.checked)} />
                Also suggest wording (Gemini; every line checked against your inputs and the orders read)
              </label>
              <div className="actions">
                <button className="primary" type="submit" disabled={!!busy || subjectShort}>{prep ? "Prepare again" : "Prepare draft"}</button>
                {subjectShort && <span className="muted">Write the subject first ({MIN_SUBJECT} characters or more).</span>}
                {prep && <span className="muted">Preparing again replaces the draft below; your inputs stay.</span>}
              </div>
            </form>
          )}
        </section>
      </div>

      {busy && <p className="busy" role="status">{busy}</p>}

      {prep && (
        <div className="draft-result">
          <section className="draft-paper" aria-label="The draft">
            <h2>3. The draft</h2>
            <p className="muted">
              Edit freely. {gaps > 0 ? `${gaps} gap${gaps === 1 ? "" : "s"} marked [ ] still to write. ` : ""}
              Numbers and dates are left for issue.
            </p>
            <textarea className="paper" value={text} onChange={(e) => setText(e.target.value)} rows={Math.min(40, Math.max(16, text.split("\n").length + 2))}
              aria-label="Draft text" spellCheck />
            {prep.suggested && <Suggested s={prep.suggested} onUse={(t) => setText(insertAfterBody(text, t))} />}
            <div className="actions">
              <button className="primary" disabled={!!busy || !text.trim() || (!target && subjectShort)} onClick={() => void save()}>
                {!target ? "Create the file and save the draft" : prep.draft.saves_as === "yellow_note" ? "Save as Yellow Note" : "Save as DFA draft"}
              </button>
              <button onClick={() => void navigator.clipboard?.writeText(text)}>Copy text</button>
              <span className="muted">
                {!target
                  ? `Opens a new e-File in your section with this subject${refs.length ? ` and ${refs.length} previous reference${refs.length === 1 ? "" : "s"}` : ""}, and saves the draft in it as ${prep.draft.saves_as === "yellow_note" ? "a Yellow Note" : "a DFA draft"}. Approval and signature stay in e-Office.`
                  : "Saving puts a draft on the file. Approval and signature stay in e-Office."}
              </span>
            </div>
            {saved && <p className="ok" role="status">{saved}{created && openFile && <> <button className="link" onClick={() => openFile(created.computerNo)}>Open the new file</button></>}</p>}
          </section>

          <aside className="draft-side" aria-label="Records and checks">
            {isNew && !created && (
              <div className="related-files">
                <h2>Earlier files on this subject</h2>
                {(prep.related_files ?? []).length === 0
                  ? <p className="muted">No earlier file on this subject was found among the files you can open.</p>
                  : <>
                    <p className="muted">Tick the ones to enter as Previous References in the new file.</p>
                    <ul>{(prep.related_files ?? []).map((f) => (
                      <li key={f.computer_no}>
                        <label className="check">
                          <input type="checkbox" checked={refs.includes(f.file_no)}
                            onChange={(e) => setRefs(e.target.checked ? [...refs, f.file_no] : refs.filter((x) => x !== f.file_no))} />
                          {f.file_no}
                        </label>
                      </li>
                    ))}</ul>
                  </>}
              </div>
            )}
            <h2>Read the following</h2>
            {prep.read_list.length === 0 && <p className="muted">No order is read yet. Add one from the close matches below.</p>}
            <ol className="readlist">
              {prep.read_list.map((i) => (
                <li key={i.canonical_id}>
                  <span>{i.label}</span>
                  {i.in_place_of.length > 0 && <span className="pill warn">in place of {i.in_place_of.length === 1 ? "a superseded order" : `${i.in_place_of.length} superseded orders`}</span>}
                  {!i.status_confirmed && <span className="pill warn">status not confirmed</span>}
                  <span className="row-actions">
                    <button className="link" onClick={() => setViewing(i.canonical_id)}>Preview</button>
                    <button className="link" onClick={() => dropRef(i.canonical_id)}>Remove</button>
                  </span>
                </li>
              ))}
            </ol>
            {prep.left_out.length > 0 && (
              <div className="leftout">
                <h3>Not read</h3>
                <ul>{prep.left_out.map((x) => <li key={x.cited}><strong>{x.cited}</strong>: {x.reason}</li>)}</ul>
              </div>
            )}

            <h2>Checks on this draft</h2>
            <Checks c={prep.checks} />

            <h2>Close matches</h2>
            <p className="muted">Found in your records by {ladderText(prep.matches.ladder)}, with what the graph says about each.</p>
            {(prep.matches.unavailable ?? []).includes("L2") && (
              <p className="caveat" role="status">Search by meaning was unavailable just now: these come from exact references and filters only.</p>
            )}
            {(prep.matches.unavailable ?? []).includes("L3") && (
              <p className="caveat" role="status">Supersession status unverified: the relations store was unavailable just now, so later orders that may replace these were not looked up. Prepare again shortly before relying on them.</p>
            )}
            {prep.matches.documents.length === 0 && <p className="muted">Nothing close was found in the records available to you.</p>}
            <ul className="matches">
              {prep.matches.documents.map((m) => <Match key={m.canonical_id} m={m} view={setViewing} download={download} add={addRef} busy={!!busy} />)}
            </ul>
          </aside>
        </div>
      )}
      {viewing && <DocumentViewer api={api} canonicalId={viewing} onClose={() => setViewing(null)} />}
    </main>
  );
}

function ladderText(l: string): string {
  const named = l.split("+").map((r) => ({ L0: "exact reference", L1: "subject filter", L2: "hybrid search", L3: "graph" }[r] ?? r));
  return named.length ? named.join(", ") : "search";
}

function Match({ m, view, download, add, busy }: {
  m: CloseMatch; view: (c: string) => void; download: (c: string) => void; add: (c: string) => void; busy: boolean;
}) {
  const st = STANDING[m.standing];
  const order = m.standing !== "not_an_order";
  return (
    <li className={`match ${st.tone}`}>
      <div className="match-head">
        <strong>{m.label}</strong>
        <span className={`pill ${st.tone}`}>{st.text}</span>
        {m.flagged.map((t) => <span key={t} className="pill bad">conflict check {t}</span>)}
      </div>
      <p className="subj">{m.subject}{m.issue_date ? ` · ${fmtDate(m.issue_date)}` : ""}</p>
      {m.use_instead && <p className="use-instead">Use instead: <strong>{m.relations.find((r) => r.other === m.use_instead)?.other_label ?? m.use_instead}</strong></p>}
      {m.relations.length > 0 && (
        <ul className="relations">{m.relations.slice(0, 6).map((r) => <li key={`${r.kind}${r.direction}${r.other}`}>{relationText(r)}</li>)}</ul>
      )}
      <div className="row-actions">
        <button className="link" onClick={() => view(m.canonical_id)}>Preview</button>
        <button className="link" onClick={() => download(m.canonical_id)}>Download</button>
        {order && !m.in_read_list && m.standing !== "repealed" && m.standing !== "expired" && (
          <button className="link" disabled={busy} onClick={() => add(m.use_instead ?? m.canonical_id)}>
            {m.use_instead ? "Add the current order to Read the following" : "Add to Read the following"}
          </button>
        )}
        {m.in_read_list && <span className="muted">In Read the following</span>}
        <span className="found">found by {m.found_by}</span>
      </div>
    </li>
  );
}

function Checks({ c }: { c: PreparedDraft["checks"] }) {
  if (c.flags.length === 0 && c.fact_gaps.length === 0 && !c.authority_message && c.status_unconfirmed.length === 0) {
    return <p className="ok">No conflict was found with the orders in your records.</p>;
  }
  return (
    <ul className="checks">
      {c.flags.map((f, n) => <li key={n} className="flag"><span className="pill bad">{f.type}</span> {f.explanation}</li>)}
      {c.authority_message && <li>{c.authority_message}</li>}
      {c.fact_gaps.map((g) => <li key={g} className="muted">Not stated in the draft: {g}</li>)}
      {c.status_unconfirmed.length > 0 && <li className="muted">Whether {c.status_unconfirmed.length} order(s) are still current could not be confirmed from your records.</li>}
    </ul>
  );
}

function Suggested({ s, onUse }: { s: NonNullable<PreparedDraft["suggested"]>; onUse: (t: string) => void }) {
  if (s.lines.length === 0) return <p className="muted suggest-none">{WHY_NO_WORDING[s.reason ?? ""] ?? "No wording was suggested."}</p>;
  return (
    <div className="suggested">
      <h3>Suggested wording</h3>
      <p className="muted">
        Written by {s.engine}{s.fallback ? " (the fallback model: the main model was unavailable)" : ""}; every line rests on the source shown.
        {s.removed > 0 ? ` ${s.removed} line${s.removed === 1 ? "" : "s"} failed the check and ${s.removed === 1 ? "was" : "were"} removed.` : ""}
      </p>
      <ol>{s.lines.map((l, n) => <li key={n}>{l.text} <span className="muted">— {l.refs.join(", ")}</span></li>)}</ol>
      <button onClick={() => onUse(s.lines.map((l) => l.text).join("\n\n"))}>Put into the draft</button>
    </div>
  );
}

/** Put suggested paragraphs where the officer writes: in place of the first unfilled gap of the
 *  body, or before the signature block, never into the record parts. */
export function insertAfterBody(text: string, add: string): string {
  const gap = /\[(What Government now order\.|The clarification or instruction\.|What is requested\.|It is proposed that …)\]/;
  if (gap.test(text)) return text.replace(gap, add.replace(/\n\n/g, " "));
  const lines = text.split("\n");
  const at = lines.findIndex((l) => /^\(BY ORDER|^Yours faithfully|^References:|^— Open points/.test(l));
  if (at < 0) return `${text}\n${add}`;
  return [...lines.slice(0, at), add, ...lines.slice(at)].join("\n");
}
