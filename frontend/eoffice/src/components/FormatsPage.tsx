import { useEffect, useState } from "react";
import type { Api } from "../api";
import type { DraftFormats } from "../types";
import type { View } from "./TopBar";

/** The draft formats (ADR-0044): what each looks like and when to use it. "Start a new draft"
 *  needs no file: the assistant prepares it from your subject and facts, and Save opens the new
 *  e-File. A draft on a file you already have starts from that file's Draft button. */
export function FormatsPage({ api, go }: { api: Api; go: (v: View) => void }) {
  const [formats, setFormats] = useState<DraftFormats | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.draftFormats().then(setFormats).catch((e: Error) => setError(e.message)); }, [api]);

  return (
    <main className="page formats">
      <div className="formats-head">
        <div>
          <h1>Draft formats</h1>
          <p className="muted">How notes and orders are laid out, and when each is used. Start a new draft from any of them: give the subject and facts, and the draft is prepared with the orders and earlier files from your records. To draft on a file you already have, open the file and choose Draft.</p>
        </div>
        <button className="primary" onClick={() => go({ kind: "newdraft" })}>New draft</button>
      </div>
      {formats?.status === "mock" && (
        <p className="mock-note">These structures are taken from orders, memos and notes in the corpus, not from an official template. Confirm them against the Office Manual before real use.</p>
      )}
      {error && <p className="error">{error}</p>}
      {!formats && !error && <p className="muted">Loading…</p>}
      {formats && (["noting", "outgoing"] as const).map((fam) => (
        <section key={fam} className="fmt-library">
          <h2>{fam === "noting" ? "Notes" : "Orders and letters (draft for approval)"}</h2>
          <div className="fmt-cards">
            {formats.formats.filter((f) => f.family === fam).map((f) => (
              <article key={f.id} className="fmt-card">
                <h3>{f.title}</h3>
                <p>{f.use_when}</p>
                <pre>{f.skeleton}</pre>
                <p className="muted small">From: {f.basis}</p>
                <div className="actions">
                  <button className="primary" onClick={() => go({ kind: "newdraft", format: f.id })}>Start a new draft</button>
                </div>
              </article>
            ))}
          </div>
        </section>
      ))}
    </main>
  );
}
