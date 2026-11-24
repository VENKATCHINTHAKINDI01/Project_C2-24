import type { ReactNode } from "react";
import {
  Activity, Archive, ArrowRightLeft, BookMarked, BookOpen, Clock, FilePlus2, FileSearch, FolderCheck,
  FolderPen, FolderPlus, Folders, Inbox, Landmark, LogOut, Mail, Moon, PanelLeft, ScanText, Send,
  Settings, Sparkles, Sun, type LucideIcon,
} from "lucide-react";
import { GoTo } from "./GoTo";
import type { FileRow, Profile } from "../types";

export type Folder = "inbox" | "created" | "closed" | "all";
export type View =
  | { kind: "files"; folder: Folder } | { kind: "file"; computerNo: string } | { kind: "newfile" }
  | { kind: "handover" } | { kind: "search" } | { kind: "receipts" }
  | { kind: "receipt"; computerNo: string } | { kind: "review" } | { kind: "monitor" } | { kind: "settings" }
  | { kind: "draft"; computerNo: string; format?: string } | { kind: "formats" }
  | { kind: "newdraft"; format?: string };

const initials = (name: string) =>
  name.replace(/^(Sri|Smt|Dr|Shri)\.?\s+/i, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

/** The header: product, Go to file, the assistant, light / dark, the signed-in officer, sign out. */
export function TopBar({ me, signOut, files = [], open = () => {}, dark = false, toggleTheme, ask, asking = false, toggleNav }: {
  me: Profile; signOut: () => void; files?: FileRow[]; open?: (computerNo: string) => void;
  dark?: boolean; toggleTheme?: () => void;
  /** the assistant panel, on every screen */
  ask?: () => void; asking?: boolean;
  /** show or hide the menu labels */
  toggleNav?: () => void;
}) {
  const name = me.name.split(" — ")[0];
  return (
    <header className="topbar">
      {toggleNav && (
        <button className="icon-btn on-chrome" onClick={toggleNav} aria-label="Show or hide the menu" title="Show or hide the menu">
          <PanelLeft size={18} aria-hidden="true" />
        </button>
      )}
      <span className="brand">
        <span className="brand-mark" aria-hidden="true"><Landmark size={18} /></span>
        <span className="brand-name">eFile</span>
        <span className="brand-sub">sandbox</span>
      </span>
      <GoTo files={files} open={open} />
      <div className="topbar-end">
        {ask && (
          <button className="ask-ai" onClick={ask} aria-expanded={asking}
            title="Ask about files and records you may see; every answer shows its sources">
            <Sparkles size={16} aria-hidden="true" /><span>Ask AI</span>
          </button>
        )}
        {toggleTheme && (
          <button className="icon-btn on-chrome theme-toggle" onClick={toggleTheme} aria-pressed={dark}
            aria-label={dark ? "Switch to the light theme" : "Switch to the dark theme"}
            title={dark ? "Switch to the light theme" : "Switch to the dark theme"}>
            {dark ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
          </button>
        )}
        <span className="divider" aria-hidden="true" />
        <span className="who">
          <span className="avatar" aria-hidden="true">{initials(name)}</span>
          <span className="who-text">
            <span className="who-name">{name}</span>
            <span className="who-post">{me.post}</span>
          </span>
        </span>
        <button className="icon-btn on-chrome signout" onClick={signOut} aria-label="Sign out" title="Sign out">
          <LogOut size={18} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}

const FOLDERS: [Folder, string, LucideIcon][] = [
  ["inbox", "Inbox", Inbox], ["created", "Created", FolderPen], ["closed", "Closed", FolderCheck], ["all", "All I can open", Folders],
];

function Item({ icon: Icon, label, on, onClick, disabled, title, count, hot }: {
  icon: LucideIcon; label: ReactNode; on?: boolean; onClick?: () => void; disabled?: boolean; title?: string;
  count?: number; hot?: boolean;
}) {
  return (
    <li>
      <button className={on ? "on" : undefined} onClick={onClick} disabled={disabled} title={title}
        aria-current={on ? "page" : undefined}>
        <Icon className="nav-icon" size={18} aria-hidden="true" />
        <span className="nav-label">{label}</span>
        {count ? <span className={`count${hot ? " hot" : ""}`} aria-label={`${count} files`}>{count}</span> : null}
      </button>
    </li>
  );
}

/** The eFile menu tree (Receipts, File), then the assistant's own pages. Items e-Office has but
 *  this sandbox does not are listed, switched off, so the shape matches what officers know. */
export function SideNav({ view, go, monitoring, counts = {}, recent = [] }: {
  view: View; go: (v: View) => void; monitoring: boolean; counts?: Record<string, number>;
  /** Files opened in this sign-in, newest first (kept only until sign-out). */
  recent?: { computerNo: string; fileNo: string }[];
}) {
  const inFile = view.kind === "file";
  return (
    <nav className="sidenav" aria-label="Main menu">
      <h2>Receipts</h2>
      <ul>
        <Item icon={Mail} label="Inbox" on={view.kind === "receipts" || view.kind === "receipt"} onClick={() => go({ kind: "receipts" })} />
        <Item icon={BookOpen} label={<>Browse &amp; diarise</>} disabled title="Not in this sandbox" />
      </ul>
      <h2>File</h2>
      <ul>
        {FOLDERS.map(([f, label, icon]) => (
          <Item key={f} icon={icon} label={label} count={counts[f]}
            on={(view.kind === "files" && view.folder === f) || (inFile && f === "all")}
            onClick={() => go({ kind: "files", folder: f })} />
        ))}
        <Item icon={FolderPlus} label="Create new" on={view.kind === "newfile"} onClick={() => go({ kind: "newfile" })} />
        <Item icon={Archive} label="Parked" disabled title="Not in this sandbox" />
      </ul>
      <h2>Drafting</h2>
      <ul>
        <Item icon={FilePlus2} label="New draft" title="Choose a format, see how it is laid out, and prepare the draft"
          on={view.kind === "newdraft" || view.kind === "formats" || view.kind === "draft"} onClick={() => go({ kind: "newdraft" })} />
      </ul>
      {recent.length > 0 && (
        <>
          <h2>Recent</h2>
          <ul className="recent">
            {recent.map((r) => (
              <Item key={r.computerNo} icon={Clock} label={r.fileNo} title={r.fileNo}
                on={view.kind === "file" && view.computerNo === r.computerNo}
                onClick={() => go({ kind: "file", computerNo: r.computerNo })} />
            ))}
          </ul>
        </>
      )}
      <h2>Assistant</h2>
      <ul>
        <Item icon={FileSearch} label="Search records" on={view.kind === "search"} onClick={() => go({ kind: "search" })} />
        <Item icon={ArrowRightLeft} label="Section handover" on={view.kind === "handover"} onClick={() => go({ kind: "handover" })} />
        <Item icon={ScanText} label="OCR review" on={view.kind === "review"} onClick={() => go({ kind: "review" })} />
        {monitoring && <Item icon={Activity} label="Monitoring" on={view.kind === "monitor"} onClick={() => go({ kind: "monitor" })} />}
      </ul>
      <h2>Personal</h2>
      <ul>
        <Item icon={Settings} label="Settings" on={view.kind === "settings"} onClick={() => go({ kind: "settings" })} />
      </ul>
      <h2>Not in this sandbox</h2>
      <ul className="off">
        <Item icon={Send} label="Dispatch" disabled title="An officer's own action; not simulated in this sandbox" />
        <Item icon={BookMarked} label="Draft register" disabled title="Not in this sandbox" />
      </ul>
    </nav>
  );
}
