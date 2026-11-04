import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { createApi } from "./api";
import { App } from "./App";
import { AssistPanel, LinkCard, SoFarCard } from "./components/AssistPanel";
import { BANNER_TEXT } from "./components/Banner";
import { outcomeLabel, yellowNoteFrom } from "./presend";
import type { PresendReport } from "./types";

const REPORT: PresendReport = {
  request_id: "r1", calibrated: false, mock_rules: true, outcome: "conflicts_found",
  flags: [
    { type: "A", cited: "AP-FIN01-GOMS-88-2022", evidence_ids: ["AP-FIN01-GOMS-88-2022", "AP-FIN01-GOMS-31-2025"],
      explanation: "Potential conflict — relies on 88/2022, superseded. Review recommended.", certain: true, review_state: "needs_review" },
    { type: "C", cited: "TRANSFER-STAFF", evidence_ids: ["AP-FIN01-GOMS-31-2025"],
      explanation: "Potential conflict — Deputy Secretary can only recommend.", certain: false, review_state: "needs_review" },
  ],
  status_unconfirmed: [], fact_gaps: [], authority_message: null,
};

/** Rendered text without React's text-node separators. */
const text = (el: React.ReactElement) => renderToString(el).replace(/<!-- -->/g, "");

describe("screens", () => {
  it("every screen starts with the mock banner (plan §11.1)", () => {
    const html = text(<App />);
    expect(html).toContain(BANNER_TEXT);
    expect(html).toContain("not NIC e-Office");
  });

  it("the assist panel shows flags, uncertainty, caveats and the drafts-only line", () => {
    const html = text(
      <AssistPanel api={createApi("U01")} computerNo="2894562" report={REPORT} onReport={() => {}} onInserted={() => {}} />,
    );
    expect(html).toContain("A · Superseded reference");
    expect(html).toContain("uncertain");
    expect(html).toContain("Approval rules are mock");
    expect(html).toContain("not calibrated");
    expect(html).toContain("Drafts only. Nothing is saved, signed or sent without the officer.");
    expect(html).toContain("Insert as Yellow Note");
  });

  it("file so far shows each note's words and source, names gaps, marks the last direction", () => {
    const html = text(
      <SoFarCard s={{
        request_id: "r", calibrated: false, mock_rules: true, computer_no: "2601155",
        file_no: "USD01-31/4/2025-VIG", chain: ["Section Officer (Vigilance)", "Deputy Secretary"],
        notes: [
          { note_no: 1, paragraphs: [1, 3], post: "Section Officer (Vigilance)", signed_at: "2025-04-09T11:05:00", text: "1. A complaint…", source: "AP-USD01-NOTE-USD0131-4-2025" },
          { note_no: 6, paragraphs: [1, 2], post: "Deputy Secretary", signed_at: "2025-07-23T11:15:00", text: "3. Submitted.", source: "AP-USD01-NOTE-USD0131-4-2025-C01" },
        ],
        last_direction: 6, gaps: [[2, 5]], gap_message: "Not available in the records available to you: Notes #2–#5. Nothing is inferred for them.",
        pending_documents: 0, pending_message: null,
      }} />,
    );
    expect(html).toContain("By post: Section Officer (Vigilance) → Deputy Secretary");
    expect(html).toContain("Source: AP-USD01-NOTE-USD0131-4-2025-C01");
    expect(html).toContain("Notes #2–#5. Nothing is inferred");
    expect(html).toContain("last direction");
  });

  it("link file lists files with their matching notes and offers only a suggested-link draft", () => {
    const html = text(
      <LinkCard
        s={{ request_id: "r", calibrated: false, mock_rules: true, computer_no: "2899017", message: null,
          suggestions: [{ file_no: "USD01-WRKS0/52/2024-WORKS", rank: 1, documents: [
            { canonical_id: "AP-USD01-NOTE-USD01WRKS0-52-2024", doc_type: "Noting", subject: "Works – Emergency restoration of culvert", issue_date: "2024-10-21", file_no: "USD01-WRKS0/52/2024-WORKS" }] }] }}
        linked={{}} busy={false} onLink={() => {}}
      />,
    );
    expect(html).toContain("USD01-WRKS0/52/2024-WORKS");
    expect(html).toContain("Emergency restoration of culvert");
    expect(html).toContain("Suggest link");
  });

  it("a review-needed outcome never reads as clear", () => {
    expect(outcomeLabel({ ...REPORT, outcome: "review_needed", flags: [] })).toMatch(/review needed/);
  });

  it("the yellow note is the flags as numbered points with their sources", () => {
    const { body, citations } = yellowNoteFrom(REPORT);
    expect(body.split("\n")).toHaveLength(3);
    expect(body).toContain("1. Superseded reference:");
    expect(body).toContain("[AP-FIN01-GOMS-88-2022; AP-FIN01-GOMS-31-2025]");
    expect(citations).toEqual(["AP-FIN01-GOMS-88-2022", "AP-FIN01-GOMS-31-2025"]);
  });
});
