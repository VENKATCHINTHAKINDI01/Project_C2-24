import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Api } from "./api";
import { DraftStudio, FromTheRecords, insertAfterBody, relationText } from "./components/DraftStudio";
import type { PreparedDraft } from "./types";
import { SideNav, TopBar } from "./components/TopBar";
import { AskAi } from "./components/AskAi";
import { RecordStatus } from "./components/Citations";
import { fromHash, toHash } from "./nav";

const text = (el: React.ReactElement) => renderToString(el).replace(/<!-- -->/g, "");

describe("draft workspace (ADR-0044)", () => {
  it("relations read as an officer would say them, both ways", () => {
    const r = { kind: "SUPERSEDES", other: "X", other_subject: "", other_label: "G.O.Ms.No.31, Finance Department" };
    expect(relationText({ ...r, direction: "out" })).toBe("Supersedes G.O.Ms.No.31, Finance Department");
    expect(relationText({ ...r, direction: "in" })).toBe("Superseded by G.O.Ms.No.31, Finance Department");
    expect(relationText({ ...r, kind: "CLARIFIES", direction: "in" })).toMatch(/^Clarified by/);
  });

  it("suggested wording goes into the officer's gap, never into the records' parts", () => {
    const draft = "Read the following:\n1. G.O.\nORDER:\n1. In the reference read above, …\n2. [What Government now order.]\n(BY ORDER AND IN THE NAME OF THE GOVERNOR OF ANDHRA PRADESH)";
    const out = insertAfterBody(draft, "Government hereby permit the transfer.");
    expect(out).toContain("2. Government hereby permit the transfer.");
    expect(out).toContain("1. In the reference read above");
    const filled = "ORDER:\n1. Done.\n(BY ORDER AND IN THE NAME OF THE GOVERNOR OF ANDHRA PRADESH)";
    expect(insertAfterBody(filled, "More.").split("\n")).toEqual(["ORDER:", "1. Done.", "More.", "(BY ORDER AND IN THE NAME OF THE GOVERNOR OF ANDHRA PRADESH)"]);
  });

  it("New draft and the draft formats are one menu item; a draft has its own address (Back / Forward)", () => {
    const nav = text(<SideNav view={{ kind: "formats" }} go={() => {}} monitoring={false} />);
    expect(nav).toMatch(/<button class="on"[^>]*>(?:(?!<\/button>).)*>New draft<\/span>/);
    expect(nav).not.toContain("Draft formats");
    expect(fromHash(toHash({ kind: "draft", computerNo: "1771342", format: "memo" }))).toEqual({ kind: "draft", computerNo: "1771342", format: "memo" });
  });

  it("a new draft needs no file: New draft is in the menu and the library offers no file picker", () => {
    expect(text(<SideNav view={{ kind: "newdraft" }} go={() => {}} monitoring={false} />)).toMatch(/<button class="on"[^>]*>(?:(?!<\/button>).)*>New draft<\/span>/);
    expect(fromHash("#/newdraft/go_ms")).toEqual({ kind: "newdraft", format: "go_ms" });
    const api = { draftFormats: () => new Promise(() => {}) } as unknown as Api;
    const studio = text(<DraftStudio api={api} back={() => {}} onSaved={() => {}} />);
    expect(studio).toContain("<h1>New draft</h1>");
    expect(studio).toContain("no file is needed yet");
    expect(studio).toContain("1. Choose a format");
    expect(studio).not.toMatch(/<select|Choose a file/);
  });

  it("Ask AI is in the top bar on every screen, and says where its answers come from", () => {
    const me = { user_id: "U01", name: "Officer A", post: "Section Officer (Estt.I)" };
    const bar = text(<TopBar me={me} signOut={() => {}} ask={() => {}} />);
    expect(bar).toMatch(/<button class="ask-ai"[^>]*>(?:(?!<\/button>).)*<span>Ask AI<\/span><\/button>/);
    expect(text(<TopBar me={me} signOut={() => {}} />)).not.toContain("Ask AI");
    const api = { chat: () => new Promise(() => {}) } as unknown as Api;
    const panel = text(<AskAi api={api} open onClose={() => {}} computerNo="1771342" fileNo="USD01-12/31/2022-ESTT.I" />);
    expect(panel).toContain("About file <strong>USD01-12/31/2022-ESTT.I</strong>");
    expect(panel).toContain("each line with its source");
    expect(text(<AskAi api={api} open={false} onClose={() => {}} />)).toContain("hidden");
  });

  it("a record says where it stands and how it entered the records", () => {
    const base = { request_id: "r", canonical_id: "AP-FIN01-GOMS-31-2025", doc_type: "Government Order", subject: "s", issue_date: null,
      version: "v", media_type: "text/plain", previewable: true, filename: "f" };
    const out = text(<RecordStatus info={{ ...base, standing: "superseded", use_instead: "AP-USD01-GOMS-9001-2026",
      history: [{ version: "a", received_at: "2026-10-02T09:00:00Z", event: "loaded" }, { version: "b", received_at: "2026-10-02T10:00:00Z", event: "draft_dispatched" }] }} />);
    expect(out).toContain("Superseded");
    expect(out).toContain("use AP-USD01-GOMS-9001-2026");
    expect(out).toContain("2 versions");
    expect(out).toContain("order issued");
    expect(text(<RecordStatus info={{ ...base, standing: "not_an_order", history: [] }} />)).toBe("");
  });
  it("beside a draft on an open file: related files, order history and people, never a blank panel", () => {
    const prep = {
      related_files: [{ file_no: "USD01-12/31/2022-ESTT.I", computer_no: "1771342" }],
      context: {
        histories: [{ order: "AP-FIN01-GOMS-31-2025", lines: [{ text: "12-05-2025: G.O.Ms.No.31 superseded G.O.Ms.No.88.", refs: [] }], in_force: [], status_reportable: false }],
        people: [{ name: "Sri Ch. Naveen Kumar", role: "Senior Assistant", officer_id: null, records: [["X", "Noting in File No.USD01-12/31/2022-ESTT.I"]] }],
      },
    } as unknown as PreparedDraft;
    const html = text(<FromTheRecords prep={prep} openFile={() => undefined} />);
    expect(html).toContain("USD01-12/31/2022-ESTT.I");
    expect(html).toContain("G.O.Ms.No.31 superseded G.O.Ms.No.88");
    expect(html).toContain("What is in force now is not stated");
    expect(html).toContain("Sri Ch. Naveen Kumar");
    expect(text(<FromTheRecords prep={{} as PreparedDraft} />)).toBe("");
  });
});

