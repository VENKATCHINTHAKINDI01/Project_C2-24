import type { ReactNode } from "react";
import {
  Activity, ArrowRightLeft, FileSearch, FolderCheck,
  FolderPen, FolderPlus, Inbox, Landmark, LogOut, Mail, Moon, PanelLeft, ScanText, Send,
  Settings, Sun, type LucideIcon,
} from "lucide-react";
import { GeneralAiIcon } from "./AssistDock";
import { GoTo } from "./GoTo";
import type { FileRow, Preferences, Profile } from "../types";
import { DisplayControls } from "./DisplayControls";

export type Folder = "inbox" | "sent" | "created" | "closed" | "all";
export type View =
  | { kind: "files"; folder: Folder } | { kind: "file"; computerNo: string } | { kind: "newfile" }
  | { kind: "handover" } | { kind: "search" } | { kind: "receipts" }
  | { kind: "receipt"; computerNo: string } | { kind: "review" } | { kind: "monitor" } | { kind: "settings" }
  | { kind: "draft"; computerNo: string; format?: string } | { kind: "formats" }
  | { kind: "newdraft"; format?: string };

const initials = (name: string) =>
  name.replace(/^(Sri|Smt|Dr|Shri)\.?\s+/i, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

/** The header: product, Go to file, the assistant, light / dark, the signed-in officer, sign out. */
export function TopBar({ me, signOut, files = [], open, dark = false, toggleTheme, ask, asking = false, toggleNav, textSize, setTextSize }: {
  me: Profile; signOut: () => void; files?: FileRow[]; open?: (computerNo: string) => void;
  dark?: boolean; toggleTheme?: () => void;
  /** the assistant panel, on every screen */
  ask?: () => void; asking?: boolean;
  /** show or hide the menu labels */
  toggleNav?: () => void;
  /** text size and language, top right */
  textSize?: Preferences["text_size"]; setTextSize?: (s: Preferences["text_size"]) => void;
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
      {open && <GoTo files={files} open={open} />}
      <div className="topbar-end">
        {textSize && setTextSize && <DisplayControls size={textSize} onSize={setTextSize} />}
        {ask && (
          <button className="ask-ai" onClick={ask} aria-expanded={asking}
            title="Ask about files and records you may see; every answer shows its sources">
            <GeneralAiIcon size={19} /><span>Office AI</span>
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
  ["inbox", "File inbox", Inbox], ["sent", "Sent", Send], ["created", "Created", FolderPen], ["closed", "Closed", FolderCheck],
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
export function SideNav({ view, go, monitoring, counts = {} }: {
  view: View; go: (v: View) => void; monitoring: boolean; counts?: Record<string, number>;
  /** Files opened in this sign-in, newest first (kept only until sign-out). */
  recent?: { computerNo: string; fileNo: string }[];
}) {
  if (monitoring) {
    // the monitoring officer has no files or receipts: the monitoring pad only (owner, 25 Nov)
    return (
      <nav className="sidenav" aria-label="Main menu">
        <h2>Monitoring</h2>
        <ul>
          <Item icon={Activity} label="Monitoring" on={view.kind === "monitor"} onClick={() => go({ kind: "monitor" })} />
        </ul>
      </nav>
    );
  }
  return (
    <nav className="sidenav" aria-label="Main menu">
      <h2>Receipts</h2>
      <ul>
        <Item icon={Mail} label="Receipt inbox" title="Letters received, not yet put in a file" on={view.kind === "receipts" || view.kind === "receipt"} onClick={() => go({ kind: "receipts" })} />
      </ul>
      <h2>File</h2>
      <ul>
        {FOLDERS.map(([f, label, icon]) => (
          <Item key={f} icon={icon} label={label} count={counts[f]}
            on={view.kind === "files" && view.folder === f}
            onClick={() => go({ kind: "files", folder: f })} />
        ))}
        <Item icon={FolderPlus} label="Create new" on={view.kind === "newfile"} onClick={() => go({ kind: "newfile" })} />
      </ul>
      <h2>Assistant</h2>
      <ul>
        <Item icon={FileSearch} label="Search records" on={view.kind === "search"} onClick={() => go({ kind: "search" })} />
        <Item icon={ArrowRightLeft} label="Section handover" on={view.kind === "handover"} onClick={() => go({ kind: "handover" })} />
        <Item icon={ScanText} label="OCR review" on={view.kind === "review"} onClick={() => go({ kind: "review" })} />
      </ul>
      <h2>Personal</h2>
      <ul>
        <Item icon={Settings} label="Settings" on={view.kind === "settings"} onClick={() => go({ kind: "settings" })} />
      </ul>
    </nav>
  );
}
