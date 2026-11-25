import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SummaryChat } from "./components/FileChatTools";
import type { FileSummary } from "./types";

const BASE: FileSummary = {
  request_id: "r1", calibrated: false, mock_rules: true, computer_no: "1", file_no: "F/1",
  notes: [{ note_no: 1, paragraphs: null, post: "Section Officer", signed_at: "2017-03-20T10:00:00",
            text: "Proposal for relaxation of the upper age limit.", source: "AP-X" }],
  chain: ["Section Officer"], last_direction: 1, gaps: [], gap_message: null,
  pending_documents: 0, pending_message: null,
  facts: ["This file is about relaxation of the upper age limit.", "The file is closed in e-Office.", "It is currently with the Secretary.", "The file is not with you now.", "The last direction in the notes is Note #1."],
  summary: { lead: "No. The file is closed and is not with you now.", lead_notes: [0, 1], points: [] },
} as unknown as FileSummary;

describe("file chat reply (25 Nov regression)", () => {
  it("answers first, cites the e-Office record, and keeps the notes readable with dd-mm-yyyy dates", () => {
    const html = renderToString(<SummaryChat s={BASE} />);
    expect(html).toContain("No. The file is closed");
    expect(html).toContain("record");
    expect(html).toContain("Proposal for relaxation of the upper age limit.");
    expect(html).toContain("20-03-2017");
    expect(html).not.toContain("answer-points");
  });
  it("falls back to the e-Office record when the model's reply did not pass the checks", () => {
    const html = renderToString(<SummaryChat s={{ ...BASE, summary: { lead: null, lead_notes: [], points: [] } }} />);
    expect(html.replace(/<!-- -->/g, "")).toContain("This file is about relaxation of the upper age limit. The file is closed in e-Office.");
  });
});

import { ChatReply } from "./components/ChatPanel";
import type { ChatTurn } from "./types";

describe("general chat small talk (25 Nov)", () => {
  it("shows the fixed reply as a chat reply, not as a missing answer", () => {
    const turn = {
      request_id: "r", session_id: "s", turn: 0, from_cache: false, used_earlier_turn: false,
      status: "chat", statements: [], review_needed: [], removed: 0, documents: [], notices: [],
      message: "Hello! Ask me about the orders.", as_of: "2026-11-25", first_cut: null,
      calibrated: false, mock_rules: true,
    } as unknown as ChatTurn;
    const html = renderToString(<ChatReply asked="hello" reply={turn} />);
    expect(html).toContain("chat-reply");
    expect(html).not.toContain("noanswer");
  });
});

import { AUTO_SUMMARY_ASK, ChatPanel } from "./components/ChatPanel";
import type { Api } from "./api";

describe("file chat opens with the summary (25 Nov, 17:33)", () => {
  it("offers no suggestion chips or file-action menu on a file", () => {
    const tools = [{ id: "summary", label: "Summarise this file", match: () => true, run: async () => null }];
    const html = renderToString(
      <ChatPanel api={{} as Api} computerNo="1" tools={tools as never} suggestions={["Where is it pending?"]} autoSummary />,
    );
    expect(html).not.toContain("About this file");
    expect(html).not.toContain("Suggested questions");
    expect(html).not.toContain("File actions");
    expect(AUTO_SUMMARY_ASK).toMatch(/end to end/);
  });
});

describe("structured file summary (25 Nov, 17:40)", () => {
  it("groups points under fixed headings and shows where the file stands from the record", () => {
    const s = { ...BASE, summary: { lead: "This file is about the age limit.", lead_notes: [1], points: [
      { text: "The proposal was submitted on 20-03-2017.", notes: [1], section: "history" },
      { text: "The Secretary agreed on 21-03-2017.", notes: [1], section: "decision" },
    ] } } as FileSummary;
    const html = renderToString(<SummaryChat s={s} />).replace(/<!-- -->/g, "");
    const order = ["What happened", "Decisions and directions", "Where the file stands", "The file is not with you now."];
    const at = order.map((t) => html.indexOf(t));
    expect(at.every((x) => x >= 0)).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
    expect(html).not.toContain("What is pending");
  });
});

describe("general chat with records but no confirmed statement (25 Nov)", () => {
  it("quotes the closest records instead of only listing them", () => {
    const turn = {
      request_id: "r", session_id: "s", turn: 1, from_cache: false, used_earlier_turn: false,
      status: "no_answer", statements: [], review_needed: [], removed: 0, documents: ["AP-A"], notices: [],
      message: "No sufficiently supported answer was found in the authorised records.", as_of: "2026-11-25",
      first_cut: null, calibrated: false, mock_rules: true,
      extracts: [{ canonical_id: "AP-A", quote: "The financial powers of the Commissioner shall be up to Rs.1.00 crore." }],
    } as unknown as ChatTurn;
    const html = renderToString(<ChatReply asked="financial powers" reply={turn} />).replace(/<!-- -->/g, "");
    expect(html).toContain("this is what the closest records say");
    expect(html).toContain("“The financial powers of the Commissioner shall be up to Rs.1.00 crore.”");
    expect(html).not.toContain("found-docs");
  });
});
