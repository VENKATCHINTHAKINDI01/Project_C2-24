import { useEffect, useState } from "react";
import type { Api } from "../api";
import type { FileRow } from "../types";

export function FileList({ api, open }: { api: Api; open: (computerNo: string) => void }) {
  const [files, setFiles] = useState<FileRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.files().then((r) => setFiles(r.files)).catch((e: Error) => setError(e.message));
  }, [api]);
  if (error) return <p className="error page">{error}</p>;
  if (!files) return <p className="muted page">Loading files…</p>;
  return (
    <main className="page">
      <h2>Files you can open</h2>
      <p className="muted">Follows your e-Office search privilege, movements and assignments, and your clearance.</p>
      <table className="grid">
        <thead><tr><th>Comp. No.</th><th>File No.</th><th>Subject</th><th>Section</th><th>Class.</th><th>State</th></tr></thead>
        <tbody>
          {files.map((f) => (
            <tr key={f.computer_no} onClick={() => open(f.computer_no)} className="clickable">
              <td>{f.computer_no}</td><td>{f.file_no}</td><td>{f.subject}</td>
              <td>{f.dealing_section}</td><td>{f.classification}</td><td>{f.state}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {files.length === 0 && <p className="muted">No files.</p>}
    </main>
  );
}
