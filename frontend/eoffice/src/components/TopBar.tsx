import { GoTo } from "./GoTo";
import type { FileRow, Profile } from "../types";

export type Folder = "inbox" | "created" | "closed" | "all";
export type View =
  | { kind: "files"; folder: Folder } | { kind: "file"; computerNo: string } | { kind: "newfile" }
  | { kind: "handover" } | { kind: "search" } | { kind: "receipts" }
  | { kind: "receipt"; computerNo: string } | { kind: "review" } | { kind: "monitor" } | { kind: "settings" }
  | { kind: "draft"; computerNo: string; format?: string } | { kind: "formats" }
  | { kind: "newdraft"; format?: string };

/** The header: product, Go to file, light / dark, the signed-in officer, sign out. */
export function TopBar({ me, signOut, files = [], open = () => {}, dark = false, toggleTheme, ask, asking = false }: {
  me: Profile; signOut: () => void; files?: FileRow[]; open?: (computerNo: string) => void;
  dark?: boolean; toggleTheme?: () => void;
  /** Ask AI, on every screen */
  ask?: () => void; asking?: boolean;
}) {
  return (
    <header className="topbar">
      <span className="brand">eFile <span className="brand-sub">sandbox</span></span>
      <GoTo files={files} open={open} />
      {ask && (
        <button className="ask-ai" onClick={ask} aria-expanded={asking}
          title="Ask about files and records you may see; every answer shows its sources">
          Ask AI
        </button>
      )}
      {toggleTheme && (
        <button className="theme-toggle" onClick={toggleTheme} aria-pressed={dark}
          title={dark ? "Switch to the light theme" : "Switch to the dark theme"}>
          <span aria-hidden="true">{dark ? "☀" : "☾"}</span> {dark ? "Light" : "Dark"}
        </button>
      )}
      <span className="who">
        <span className="who-name">{me.name.split(" — ")[0]}</span>
        <span className="who-post">{me.post}</span>
      </span>
      <button className="signout" onClick={signOut}>Sign out</button>
    </header>
  );
}

const FOLDERS: [Folder, string][] = [["inbox", "Inbox"], ["created", "Created"], ["closed", "Closed"], ["all", "All I can open"]];

/** The eFile menu tree (Receipts, File), then the assistant's own pages. Items e-Office has but
 *  this sandbox does not are listed, switched off, so the shape matches what officers know. */
export function SideNav({ view, go, monitoring, counts = {}, recent = [] }: {
  view: View; go: (v: View) => void; monitoring: boolean; counts?: Record<string, number>;
  /** Files opened in this sign-in, newest first (kept only until sign-out). */
  recent?: { computerNo: string; fileNo: string }[];
}) {
  const on = (test: boolean) => (test ? "on" : undefined);
  const inFile = view.kind === "file";
  return (
    <nav className="sidenav" aria-label="Main menu">
      <h2>Receipts</h2>
      <ul>
        <li><button className={on(view.kind === "receipts" || view.kind === "receipt")} onClick={() => go({ kind: "receipts" })}>Inbox</button></li>
        <li><button disabled title="Not in this sandbox">Browse &amp; diarise</button></li>
      </ul>
      <h2>File</h2>
      <ul>
        <li><button className={on(view.kind === "newfile")} onClick={() => go({ kind: "newfile" })}>Create new</button></li>
        <li><button className={on(view.kind === "newdraft")} onClick={() => go({ kind: "newdraft" })}>New draft</button></li>
        <li><button className={on(view.kind === "formats" || view.kind === "draft")} onClick={() => go({ kind: "formats" })}>Draft formats</button></li>
        {FOLDERS.map(([f, label]) => (
          <li key={f}>
            <button className={on((view.kind === "files" && view.folder === f) || (inFile && f === "all"))}
              onClick={() => go({ kind: "files", folder: f })}>
              {label}{counts[f] ? <span className="count" aria-label={`${counts[f]} files`}>{counts[f]}</span> : null}
            </button>
          </li>
        ))}
        <li><button disabled title="Not in this sandbox">Parked</button></li>
      </ul>
      {recent.length > 0 && (
        <>
          <h2>Recent</h2>
          <ul className="recent">
            {recent.map((r) => (
              <li key={r.computerNo}>
                <button className={on(view.kind === "file" && view.computerNo === r.computerNo)} title={r.fileNo}
                  onClick={() => go({ kind: "file", computerNo: r.computerNo })}>{r.fileNo}</button>
              </li>
            ))}
          </ul>
        </>
      )}
      <h2>Assistant</h2>
      <ul>
        <li><button className={on(view.kind === "search")} onClick={() => go({ kind: "search" })}>Search records</button></li>
        <li><button className={on(view.kind === "handover")} onClick={() => go({ kind: "handover" })}>Section handover</button></li>
        <li><button className={on(view.kind === "review")} onClick={() => go({ kind: "review" })}>OCR review</button></li>
        {monitoring && <li><button className={on(view.kind === "monitor")} onClick={() => go({ kind: "monitor" })}>Monitoring</button></li>}
      </ul>
      <h2>Personal</h2>
      <ul>
        <li><button className={on(view.kind === "settings")} onClick={() => go({ kind: "settings" })}>Settings</button></li>
      </ul>
      <h2>Not in this sandbox</h2>
      <ul className="off">
        <li><button disabled title="An officer's own action; not simulated in this sandbox">Dispatch</button></li>
        <li><button disabled title="Not in this sandbox">Draft register</button></li>
      </ul>
    </nav>
  );
}
