import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { createApi } from "./api";
import { App } from "./App";
import { AssistPanel, BriefCard, LinkCard, SoFarCard } from "./components/AssistPanel";
import { BANNER_TEXT } from "./components/Banner";
import { NoticesPanel, ReceiptAssistCard } from "./components/Receipts";
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

  it("receipt assist shows the summary, which order each flag is about, and never forces a file", () => {
    const html = text(
      <ReceiptAssistCard r={{
        request_id: "r", calibrated: false, mock_rules: true, computer_no: "9100008", as_of: "2026-10-02",
        document: { canonical_id: "AP-FIN01-GORT-1184-2025", doc_type: "Government Order", subject: "Continuation…", issue_date: "2025-03-21", file_no: null },
        summary: ["Government Order from Finance, dated 21-03-2025: Continuation…", "Cites: AP-FIN01-GOMS-40-2020 (28-04-2020)."],
        cited: ["AP-FIN01-GOMS-40-2020"], status_unconfirmed: ["AP-FIN01-GOMS-40-2020"], message: null,
        flags: [{ type: "F", about: "this order", cited: "AP-FIN01-GORT-1184-2025", evidence_ids: [], explanation: "Potential conflict — validity ended on 31-03-2026. Review recommended.", certain: true, review_state: "needs_review" }],
        put_in: { suggestion: "new_file", files: [], related_files: ["USD01-14/6/2026-ESTT.I"] },
      }} />,
    );
    expect(html).toContain("F · Temporal mismatch — this order");
    expect(html).toContain("open a new file");
    expect(html).toContain("Related (for reference only, not the file to put this in)");
  });

  it("a notice names the change and only the open files that rely on the old order", () => {
    const html = text(
      <NoticesPanel n={{ request_id: "r", calibrated: false, mock_rules: true, notices: [{
        change: "SUPERSEDES",
        new: { canonical_id: "AP-FIN01-GOMS-31-2025", doc_type: "Government Order", subject: "General Transfers 2025", issue_date: "2025-05-12" },
        changed: { canonical_id: "AP-FIN01-GOMS-88-2022", doc_type: "Government Order", subject: "General Transfers 2022", issue_date: "2022-06-03" },
        files: [{ file_no: "USD01-12/19/2026-ESTT.I", citing_doc: "AP-USD01-NOTE-USD0112-19-2026" }],
      }] }} />,
    );
    expect(html).toContain("AP-FIN01-GOMS-31-2025 supersedes AP-FIN01-GOMS-88-2022");
    expect(html).toContain("Open files that rely on AP-FIN01-GOMS-88-2022: USD01-12/19/2026-ESTT.I");
  });

  it("the approval brief shows the proposal, what it relies on, flags and precedents", () => {
    const html = text(
      <BriefCard b={{
        request_id: "r", calibrated: false, mock_rules: true, computer_no: "2894562",
        file_no: "USD01-12/19/2026-ESTT.I", subject: "Transfer", draft_id: "AP-USD01-NOTE-USD0112-19-2026",
        proposal: { action: "transfer", post_level: "staff", amount_rupees: null, proposed_authority: "Deputy Secretary",
          proposal_date: "2026-09-22", evidence: { proposed_authority: "the Deputy Secretary may kindly approve" }, not_stated: [] },
        chain: ["Assistant Section Officer (Estt.I)"],
        put_up: { post: "Assistant Section Officer (Estt.I)", signed_at: "2026-09-22T12:10:00", source: "x" },
        governing: [
          { cited: "AP-FIN01-GOMS-88-2022", found: true, status: "superseded", by: "AP-FIN01-GOMS-31-2025", current_version: null, message: "I can't confirm which version is current…" },
          { cited: "AP-FIN01-GOMS-104-2026", found: false, status: null, by: null, current_version: null, message: "Not found in the records available to you." },
        ],
        presend: { ...REPORT },
        precedents: [{ file_no: "USD01-12/58/2025-ESTT.I", documents: [{ canonical_id: "n", doc_type: "Noting", subject: "Sri K. Venkata Ramana", issue_date: null, file_no: null }] }],
        movement: [],
      }} />,
    );
    expect(html).toContain("approval sought from Deputy Secretary");
    expect(html).toContain("AP-FIN01-GOMS-88-2022: superseded by AP-FIN01-GOMS-31-2025");
    expect(html).toContain("AP-FIN01-GOMS-104-2026: not found");
    expect(html).toContain("C · Procedure / authority (uncertain)");
    expect(html).toContain("Put up by Assistant Section Officer (Estt.I) on 2026-09-22");
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
