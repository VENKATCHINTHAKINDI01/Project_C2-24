import { useState } from "react";
import type { Api } from "../api";
import type { PreviousRefs } from "../types";

/** Touchpoint 5 — creating a file: earlier files on the same subject are suggested as Previous
 *  References; the officer ticks the ones to enter and creates the file (simulated e-Office). */
export function NewFilePanel({ api, open }: { api: Api; open: (computerNo: string) => void }) {
  const [subject, setSubject] = useState("");
  const [refs, setRefs] = useState<PreviousRefs | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const suggest = () => {
    setBusy(true); setError(null); setChosen([]);
    api.previousRefs(subject).then(setRefs).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  const create = () => {
    setBusy(true); setError(null);
    api.createFile(subject, chosen).then((r) => open(r.file.computer_no))
      .catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  const toggle = (f: string) => setChosen((c) => (c.includes(f) ? c.filter((x) => x !== f) : [...c, f]));
  return (
    <section className="newfile">
      <h1>Create a file</h1>
      <p className="muted">Write the subject the way the file will be known. The assistant offers earlier files on the same subject as Previous References; you choose which to enter.</p>
      <label className="muted" htmlFor="nf-subject">Subject</label>
      <textarea id="nf-subject" rows={2} value={subject} onChange={(e) => setSubject(e.target.value)}
        placeholder="Establishment – Sri …, Senior Assistant – Request for transfer on spouse grounds – Reg." />
      <div className="actions">
        <button disabled={busy || subject.trim().length < 10} onClick={suggest}>Suggest previous references</button>
        <button className="primary" disabled={busy || subject.trim().length < 10} onClick={create}>
          Create file{chosen.length ? ` with ${chosen.length} reference(s)` : ""}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {refs && refs.suggestions.length === 0 && <p className="muted">{refs.message}</p>}
      {refs && refs.suggestions.length > 0 && (
        <ul className="refs">
          {refs.suggestions.map((s) => (
            <li key={s.file_no}>
              <label>
                <input type="checkbox" checked={chosen.includes(s.file_no)} onChange={() => toggle(s.file_no)} />{" "}
                <strong>{s.file_no}</strong> <span className="muted">(Comp. No. {s.computer_no})</span>
              </label>
              {s.documents[0]?.subject && <div className="sub">{s.documents[0].subject}</div>}
            </li>
          ))}
        </ul>
      )}
      <p className="footnote">Suggestions only: you choose which earlier files to enter as Previous References.</p>
    </section>
  );
}
