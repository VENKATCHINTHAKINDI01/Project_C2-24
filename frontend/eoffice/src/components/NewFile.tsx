import { useRef, useState } from "react";
import { FileUp, Paperclip, Sparkles, X } from "lucide-react";
import type { Api } from "../api";
import type { PreviousRefs } from "../types";
import { DocumentViewer } from "./Citations";

/** Touchpoint 5 — creating a file: earlier files on the same subject are suggested as Previous
 *  References (with document preview/download), plus file context (with AI upload-extract &
 *  polish icons) and attachments forwarded to upper authorities. */
export function NewFilePanel({ api, open }: { api: Api; open: (computerNo: string) => void }) {
  const [subject, setSubject] = useState("");
  const [content, setContent] = useState("");
  const [refs, setRefs] = useState<PreviousRefs | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [attachments, setAttachments] = useState<File[]>([]);
  const [previewDoc, setPreviewDoc] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [aiBusy, setAiBusy] = useState<"extract" | "polish" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const extractInputRef = useRef<HTMLInputElement>(null);
  const attachInputRef = useRef<HTMLInputElement>(null);

  const suggest = () => {
    setBusy(true); setError(null); setChosen([]);
    api.previousRefs(subject).then(setRefs).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };

  const create = async () => {
    setBusy(true); setError(null);
    try {
      const r = await api.createFile(subject, chosen, content);
      for (const f of attachments) {
        await api.attach(r.file.computer_no, f);
      }
      open(r.file.computer_no);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onExtractFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setAiBusy("extract"); setError(null);
    try {
      const res = await api.extractText(file);
      setContent((prev) => (prev.trim() ? `${prev.trim()}\n\n${res.text}` : res.text));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAiBusy(null);
    }
  };

  const onPolish = async () => {
    setAiBusy("polish"); setError(null);
    try {
      const res = await api.polishContext(subject, content);
      setContent(res.text);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAiBusy(null);
    }
  };

  const onPickAttachments = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!picked.length) return;
    setAttachments((prev) => [...prev, ...picked]);
  };

  const toggle = (f: string) => setChosen((c) => (c.includes(f) ? c.filter((x) => x !== f) : [...c, f]));
  const working = busy || aiBusy !== null;

  return (
    <section className="newfile">
      <h1>Create a file</h1>
      <p className="muted">Write the subject and context for the new file. The assistant offers earlier files on the same subject as Previous References; you choose which to enter.</p>
      <label className="muted" htmlFor="nf-subject">Subject</label>
      <textarea id="nf-subject" rows={2} value={subject} onChange={(e) => setSubject(e.target.value)}
        placeholder="Establishment – Sri …, Senior Assistant – Request for transfer on spouse grounds – Reg." />

      <div className="context-box">
        <div className="context-head">
          <label className="muted" htmlFor="nf-context">Context</label>
          <div className="context-icons">
            <input ref={extractInputRef} type="file" hidden accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.heic,.docx,.txt"
              onChange={onExtractFile} aria-label="Upload PDF or image to extract text" />
            <button type="button" className="icon-btn" disabled={working}
              title="Extract text from PDF or image" aria-label="Extract text from PDF or image"
              onClick={() => extractInputRef.current?.click()}>
              <FileUp size={15} aria-hidden="true" />
            </button>
            <button type="button" className="icon-btn" disabled={working || content.trim().length < 5}
              title="AI Polish" aria-label="AI Polish" onClick={onPolish}>
              <Sparkles size={15} aria-hidden="true" />
            </button>
          </div>
        </div>
        <textarea id="nf-context" rows={5} value={content} onChange={(e) => setContent(e.target.value)}
          placeholder="Write the file content or opening note, or use the upload icon above to extract text from a PDF or image." />
      </div>

      <div className="actions">
        <button disabled={working || subject.trim().length < 10} onClick={suggest}>Suggest previous references</button>
        <input ref={attachInputRef} type="file" multiple hidden
          accept=".pdf,.docx,.txt,.jpg,.jpeg,.png,.heic,.tif,.tiff" onChange={onPickAttachments} />
        <button type="button" disabled={working} onClick={() => attachInputRef.current?.click()}>
          <Paperclip size={14} aria-hidden="true" /> Attach files
        </button>
        <button className="primary" disabled={working || subject.trim().length < 10} onClick={create}>
          Create file{chosen.length ? ` with ${chosen.length} reference(s)` : ""}
        </button>
      </div>

      {attachments.length > 0 && (
        <ul className="att-queue" aria-label="Queued attachments">
          {attachments.map((f, i) => (
            <li key={`${f.name}-${i}`} className="att-chip">
              <span>{f.name}</span>
              <button type="button" className="linklike" aria-label={`Remove ${f.name}`}
                onClick={() => setAttachments((prev) => prev.filter((_, idx) => idx !== i))}>
                <X size={12} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}

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
              {s.documents.length > 0 && (
                <div className="ref-docs">
                  {s.documents.map((d) => (
                    <a key={d.canonical_id} href="#" role="button" className="open sub"
                      title={`Preview and download ${d.canonical_id}`}
                      onClick={(e) => { e.preventDefault(); setPreviewDoc(d.canonical_id); }}>
                      {d.subject ? `${d.canonical_id} — ${d.subject}` : d.canonical_id}
                    </a>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {previewDoc && <DocumentViewer api={api} canonicalId={previewDoc} onClose={() => setPreviewDoc(null)} />}
      <p className="footnote">Suggestions only: you choose which earlier files to enter as Previous References.</p>
    </section>
  );
}
