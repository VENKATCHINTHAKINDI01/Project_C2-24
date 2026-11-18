import type { Folder, View } from "./components/TopBar";

/**
 * Screen ↔ address (ADR-0041). Each screen has its own address after `#`, so the browser's
 * Back and Forward buttons move between screens, a reload stays on the same screen, and an
 * address can be bookmarked. The address only says WHICH screen; whether the officer may see
 * it is decided by the server on every request, exactly as when the screen is opened by a click.
 */
const FOLDERS: readonly Folder[] = ["inbox", "created", "closed", "all"];
const ID = /^[A-Za-z0-9._-]{1,64}$/; // Computer Nos; anything else is not an address of ours
const FORMAT = /^[a-z][a-z0-9_]{1,40}$/; // a draft format id (config/draft_formats.yaml)

export const HOME: View = { kind: "files", folder: "inbox" };

export function toHash(v: View): string {
  switch (v.kind) {
    case "files": return `#/files/${v.folder}`;
    case "file": return `#/file/${encodeURIComponent(v.computerNo)}`;
    case "receipt": return `#/receipt/${encodeURIComponent(v.computerNo)}`;
    case "draft": return `#/draft/${encodeURIComponent(v.computerNo)}${v.format ? `/${v.format}` : ""}`;
    case "newdraft": return `#/newdraft${v.format ? `/${v.format}` : ""}`;
    default: return `#/${v.kind}`;
  }
}

/** The screen an address names, or null if it names none (unknown, malformed, hostile). */
export function fromHash(hash: string): View | null {
  const parts = hash.replace(/^#\/?/, "").split("/");
  const [kind, arg, extra, more] = parts;
  if (more !== undefined || (extra !== undefined && kind !== "draft")) return null;
  if (extra !== undefined && !FORMAT.test(extra)) return null;
  if (kind === "newdraft") { // a new matter: the only part after it is a format id
    if (extra !== undefined) return null;
    if (arg === undefined) return { kind };
    return FORMAT.test(arg) ? { kind, format: arg } : null;
  }
  let id: string | null = null;
  if (arg !== undefined) {
    try { id = decodeURIComponent(arg); } catch { return null; }
    if (!ID.test(id)) return null;
  }
  switch (kind) {
    case "files": return id && (FOLDERS as readonly string[]).includes(id) ? { kind: "files", folder: id as Folder } : null;
    case "file": return id ? { kind: "file", computerNo: id } : null;
    case "receipt": return id ? { kind: "receipt", computerNo: id } : null;
    case "draft": return id ? { kind: "draft", computerNo: id, ...(extra ? { format: extra } : {}) } : null;
    case "newfile": case "handover": case "search": case "receipts": case "review": case "monitor": case "settings": case "formats":
      return id === null ? { kind } : null;
    default: return null;
  }
}

/** The address the browser is on ("" outside a browser, e.g. server rendering in tests). */
export const currentHash = (): string => (typeof window === "undefined" ? "" : window.location.hash);
