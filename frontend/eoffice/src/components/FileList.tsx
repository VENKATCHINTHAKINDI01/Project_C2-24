import { Folders } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Api } from "../api";
import { fmtDate, fmtDateTime } from "../format";
import { rowKeys } from "../keys";
import { usePrefs } from "../prefs";
import type { FileRow } from "../types";
import { DigestPanel } from "./Digest";
import type { Folder } from "./TopBar";

const TITLE: Record<Folder, string> = {
  inbox: "Inbox", sent: "Sent by you", created: "Created by you", closed: "Closed files", all: "All files you can open",
};
const EMPTY: Record<Folder, string> = {
  inbox: "No file is waiting with you.",
  sent: "No file you sent is waiting with another officer.",
  created: "You have not created a file. Use Create new to open one.",
  closed: "No closed file is open to you.",
  all: "No file is open to you.",
};

function inFolder(f: FileRow, folder: Folder): boolean {
  if (folder === "inbox") return !!f.with_me;
  if (folder === "sent") return !!f.sent_by_me;
  if (folder === "created") return !!f.created_by_me;
  if (folder === "closed") return f.state === "closed";
  return true;
}

/** An eFile folder (Inbox, Created, Closed) or every file the officer can open — e-Office's
 *  reach (search privilege, movements, assignments) and C2-24's clearance check. */
/** "overdue" or "due soon" beside a due date (Settings: how many days count as soon; 0 = off). */
export function dueTag(due: string | null | undefined, days: number, today: Date = new Date()) {
  if (!due || days <= 0) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(due);
  if (!m) return null;
  const start = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  const left = Math.round((Date.UTC(+m[1], +m[2] - 1, +m[3]) - start) / 86_400_000);
  if (left < 0) return <span className="tag overdue">overdue</span>;
  if (left <= days) return <span className="tag due">{left === 0 ? "due today" : `due in ${left} day${left === 1 ? "" : "s"}`}</span>;
  return null;
}

export function FileList({ api, open, folder }: { api: Api; open: (computerNo: string) => void; folder: Folder }) {
  const [files, setFiles] = useState<FileRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [find, setFind] = useState("");
  const { due_soon_days: dueSoon } = usePrefs();
  useEffect(() => {
    api.files().then((r) => setFiles(r.files)).catch((e: Error) => setError(e.message));
  }, [api]);
  const rows = useMemo(() => {
    const q = find.trim().toLowerCase();
    return (files ?? []).filter((f) => inFolder(f, folder) &&
      (!q || f.subject.toLowerCase().includes(q) || f.file_no.toLowerCase().includes(q) || f.computer_no.includes(q)));
  }, [files, folder, find]);
  if (error) return <main className="page"><p className="error">Could not load your files: {error}</p></main>;
  if (!files) return <main className="page"><p className="muted">Loading files…</p></main>;
  return (
    <main className="page">
      {folder === "inbox" && <DigestPanel api={api} open={open} />}
      <div className="listhead">
        <h1>{TITLE[folder]}</h1>
        <input type="search" aria-label="Filter by subject or file number" placeholder="Filter by subject or file number"
          value={find} onChange={(e) => setFind(e.target.value)}
          onKeyDown={(e) => { // ↓ from the filter goes to the first row
            if (e.key !== "ArrowDown") return;
            const first = document.querySelector<HTMLElement>("table.register tbody tr[tabindex]");
            if (first) { e.preventDefault(); first.focus(); }
          }} />
      </div>
      {rows.length > 0 && <table className="grid register">
        <thead>
          <tr>
            <th className="num">Comp. No.</th><th>File No.</th><th>Subject</th>
            {folder === "inbox" && <><th>Sent by</th><th>Received</th><th>Due</th></>}
            {folder === "sent" && <><th>With</th><th>Sent on</th></>}
            {folder === "created" && <><th>Created</th><th>With</th><th>State</th></>}
            {(folder === "closed" || folder === "all") && <><th>Section</th><th>Classification</th>{folder === "all" && <th>State</th>}</>}
          </tr>
        </thead>
        <tbody>
          {rows.map((f) => (
            <tr key={f.computer_no} className="clickable" tabIndex={0}
              onClick={() => open(f.computer_no)} onKeyDown={(e) => rowKeys(e, () => open(f.computer_no))}>
              <td className="num">{f.computer_no}</td>
              <td className="fileno">{f.file_no}</td>
              <td>{f.subject}{f.priority && f.priority !== "normal" && <span className="tag">{f.priority}</span>}</td>
              {folder === "inbox" && <><td>{f.sent_by_post ?? "—"}</td><td className="date">{fmtDateTime(f.received_on)}</td>
                <td className="date">{fmtDate(f.due_on)}{dueTag(f.due_on, dueSoon)}</td></>}
              {folder === "sent" && <><td>{f.holder_post ?? "—"}</td><td className="date">{fmtDateTime(f.received_on)}</td></>}
              {folder === "created" && <><td className="date">{fmtDate(f.created_on)}</td><td>{f.state === "closed" ? "—" : f.holder_post ?? "—"}</td><td>{f.state}</td></>}
              {(folder === "closed" || folder === "all") && <><td>{f.dealing_section}</td><td><span className={`mark ${f.classification.toLowerCase()}`}>{f.classification}</span></td>{folder === "all" && <td>{f.state}</td>}</>}
            </tr>
          ))}
        </tbody>
      </table>}
      {rows.length === 0 && <div className="empty-state"><Folders size={28} aria-hidden="true" /><p>{find ? "No file matches this filter." : EMPTY[folder]}</p></div>}
    </main>
  );
}
