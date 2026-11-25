import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { createApi } from "./api";
import { App } from "./App";
import { AssistPanel, BriefCard, DfaCard, FirstCutCard, LinkCard, NoteReferenceCard, ReferenceCard, SoFarCard } from "./components/AssistPanel";
import { BANNER_TEXT } from "./components/Banner";
import { CitationLegend, DocumentViewer, HighlightedText } from "./components/Citations";
import { ChatPanel, ChatReply } from "./components/ChatPanel";
import { Questions, WhatIsAsked } from "./components/MonitorPad";
import { OcrReview } from "./components/OcrReview";
import { SideNav } from "./components/TopBar";
import { NoticesPanel, ReceiptAssistCard } from "./components/Receipts";
import { outcomeLabel, yellowNoteFrom } from "./presend";
import type { ChatTurn, Highlight, PresendReport } from "./types";

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

  it("a cited order awaiting review is not reported as missing", () => {
    const report: PresendReport = { ...REPORT, outcome: "review_needed", flags: [], awaiting_review: ["AP-USD01-CIRMEMO-USD01WRKS0-9-2023"] };
    const html = text(
      <AssistPanel api={createApi("U03")} computerNo="2894570" report={report} onReport={() => {}} onInserted={() => {}} />,
    );
    expect(html).toContain("may be among your records awaiting review");
    expect(html).toContain("AP-USD01-CIRMEMO-USD01WRKS0-9-2023");
    expect(html).not.toContain("E · ");
  });

  it("note references show the paragraph, its source and an insert-on-click button", () => {
    const html = text(
      <NoteReferenceCard
        r={{
          request_id: "r", calibrated: false, mock_rules: true, computer_no: "2601155", matched_by: "keywords",
          matching: "keyword stand-in (not semantic)", message: null,
          suggestions: [{
            kind: "previous_note", target_id: "2601155-N1", note_no: 1, paragraph: 3, page_from: null, page_to: null,
            text: "3. It is proposed that a preliminary enquiry may be ordered…", source: "AP-USD01-NOTE-USD0131-4-2025",
            matched_terms: ["enquir", "preliminar", "propos"], insert_text: "Note #1, para 3",
          }],
        }}
        done={{}}
        busy={false}
        onInsert={() => {}}
      />,
    );
    expect(html).toContain("Note #1, para 3");
    expect(html).toContain("2601155-N1");
    expect(html).toContain("Source: AP-USD01-NOTE-USD0131-4-2025");
    expect(html).toContain("Insert reference");
    expect(html).toContain("check it is the right paragraph");
  });

  it("a local reference shows both paragraphs and never calls the later order current unconfirmed", () => {
    const html = text(
      <ReferenceCard r={{
        request_id: "r", calibrated: false, mock_rules: true, found: true,
        documents: [{ canonical_id: "AP-FIN01-GOMS-88-2022", doc_type: "Government Order", subject: "Transfers 2022", issue_date: "2022-06-03", file_no: null }],
        status: "superseded", by: "AP-FIN01-GOMS-31-2025", since: "2025-05-12", current_version: null,
        message: "I can't confirm which version is current from the records available to you.",
        paragraph: "2.v",
        cited_clause: { clause_id: "AP-FIN01-GOMS-88-2022#para-2.v", text: "(v) Spouse cases … preference." },
        successor_clause: { clause_id: "AP-FIN01-GOMS-31-2025#para-2.v", text: "(v) Spouse cases … vacancy." },
        successor_is_current: false,
        clause_note: "Same paragraph number in the order that superseded it — check it covers the same point.",
      }} />,
    );
    expect(html).toContain("by <strong>AP-FIN01-GOMS-31-2025</strong> from 12-05-2025");
    expect(html).toContain("AP-FIN01-GOMS-31-2025#para-2.v");
    expect(html).toContain("check it covers the same point");
    expect(html).not.toContain("Current version");
    expect(html).not.toContain(" · current");
  });

  it("the DFA card lists what to read, what was left out and why, and saves only on click", () => {
    const d = {
      request_id: "r", calibrated: false, mock_rules: true, computer_no: "2894562", file_no: "USD01-12/19/2026-ESTT.I",
      draft_note: "n", abstract: "Establishment – Transfer – Orders – Issued.",
      read_list: [{ canonical_id: "AP-FIN01-GOMS-31-2025", doc_type: "Government Order", subject: "General Transfers 2025",
        issue_date: "2025-05-12", in_place_of: ["AP-FIN01-GOMS-88-2022"], cited_in_note: false, status_confirmed: false }],
      left_out: [{ cited: "AP-FIN01-GOMS-104-2026", reason: "not found in the records available to you" }],
      flags: REPORT.flags ?? [], caveats: ["Some records you may see are awaiting review."],
      body: "DRAFT FOR APPROVAL", citations: ["AP-FIN01-GOMS-31-2025"], order_paragraphs: "not drafted (needs Gemini)",
    };
    const html = text(<DfaCard d={d} body={d.body} made={null} busy={false} onEdit={() => {}} onCreate={() => {}} />);
    expect(html).toContain("in place of AP-FIN01-GOMS-88-2022");
    expect(html).toContain("Not listed: AP-FIN01-GOMS-104-2026");
    expect(html).toContain("status not confirmed");
    expect(html).toContain("Open points travel with the draft");
    expect(html).toContain("Create DFA draft");
    const saved = text(<DfaCard d={d} body={d.body} made="MOCK-DRAFT-9" busy={false} onEdit={() => {}} onCreate={() => {}} />);
    expect(saved).toContain("Not approved, signed or issued.");
  });

  it("the first-cut card quotes each point with its source and inserts only on click", () => {
    const c = {
      request_id: "r", calibrated: false, mock_rules: true, computer_no: "2894562", file_no: "USD01-12/19/2026-ESTT.I",
      draft_note: "n", ground: "spouse",
      orders: [{ canonical_id: "AP-FIN01-GOMS-31-2025", doc_type: "Government Order", subject: "General Transfers 2025",
        issue_date: "2025-05-12", in_place_of: ["AP-FIN01-GOMS-88-2022"], cited_in_note: false, status_confirmed: false }],
      left_out: [],
      points: [{ topic: "Ban / relaxation window", clause_id: "AP-FIN01-GOMS-31-2025#para-3", text: "3. After 31-05-2025 the ban on transfers shall come into force again." }],
      precedents: [{ file_no: "USD01-12/77/2023-ESTT.I", source: "AP-USD01-NOTE-USD0112-77-2023", note_no: 5, paragraph: 8,
        decided_on: "2023-09-02", decision: "8. Not agreed at present, as the ban on transfers is in force.", windows: [], in_window: false }],
      flags: REPORT.flags ?? [], body: "FIRST-CUT NOTE", citations: ["AP-FIN01-GOMS-31-2025"], note_text: "not drafted (needs Gemini)",
    };
    const html = text(<FirstCutCard c={c} body={c.body} made={null} busy={false} onEdit={() => {}} onInsert={() => {}} />);
    expect(html).toContain("in place of AP-FIN01-GOMS-88-2022");
    expect(html).toContain("Ban / relaxation window · AP-FIN01-GOMS-31-2025#para-3");
    expect(html).toContain("02-09-2023");
    expect(html).toContain("outside every relaxation window in your records");
    expect(html).toContain("Insert as Yellow Note");
    const done = text(<FirstCutCard c={c} body={c.body} made="MOCK-DRAFT-3" busy={false} onEdit={() => {}} onInsert={() => {}} />);
    expect(done).toContain("Not confirmed or sent.");
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

describe("citation highlights and preview (ADR-0014, ADR-0015)", () => {
  const NOTE = "2. As per G.O.Ms.No.88 Dt.03-06-2022 and G.O.Ms.No.104 Dt.02-01-2026; see file No. FIN01-X/1/2025-HR.I and file No. USD01-31/4/2025-VIG.";
  const at = (s: string) => NOTE.indexOf(s);
  const h = (raw: string, state: Highlight["state"], extra: Partial<Highlight> = {}): Highlight => ({
    start: at(raw), end: at(raw) + raw.length, raw, kind: "order", state, canonical_id: null, file_no: null, flags: [], ...extra,
  });
  const MARKS: Highlight[] = [
    h("G.O.Ms.No.88 Dt.03-06-2022", "conflict", { canonical_id: "AP-FIN01-GOMS-88-2022", flags: [
      { type: "A", cited: "AP-FIN01-GOMS-88-2022", evidence_ids: [], explanation: "Potential conflict — superseded.", certain: true, review_state: "needs_review" }] }),
    h("G.O.Ms.No.104 Dt.02-01-2026", "not_found"),
    h("FIN01-X/1/2025-HR.I", "file", { kind: "efile", file_no: "FIN01-X/1/2025-HR.I" }),
    h("USD01-31/4/2025-VIG", "file", { kind: "efile", file_no: "USD01-31/4/2025-VIG" }),
  ];
  const render = (marks: Highlight[]) => text(
    <HighlightedText text={NOTE} highlights={marks} onOpenDoc={() => {}} onOpenFile={() => {}} fileNos={new Set(["FIN01-X/1/2025-HR.I"])} />,
  );

  it("shows the note exactly as written, with every citation marked", () => {
    const html = render(MARKS);
    expect(html.replace(/<[^>]+>/g, "").replace(/&amp;/g, "&")).toBe(`${NOTE}`);
    expect(html).toContain('class="cite conflict open"');
    expect(html).toContain("Potential conflict — superseded.");
    expect(html).toContain("Click to open AP-FIN01-GOMS-88-2022");
  });

  it("links only orders the officer may open and files in their own list", () => {
    const html = render(MARKS);
    // ADR-0019: a citation not found is clickable for the explanation, but carries no ID or document link
    expect(html).toMatch(/<a[^>]*class="cite not_found"[^>]*>G\.O\.Ms\.No\.104/);
    expect(html).not.toContain("AP-FIN01-GOMS-104-2026");
    expect(html).toMatch(/<a[^>]*class="cite file open"[^>]*>FIN01-X\/1\/2025-HR\.I/);
    expect(html).toMatch(/<mark class="cite file"[^>]*>USD01-31\/4\/2025-VIG/);
    expect(html).toContain("Not among the files you can open");
    expect(html).toContain("request access or approval from the competent authority through e-Office");
    expect((html.match(/<a /g) ?? []).length).toBe(3);
    expect((html.match(/class="cite [a-z_]+ open"/g) ?? []).length).toBe(2);
    expect(html).toContain("may not be in C2-24&#x27;s collection yet");
  });

  it("ignores overlapping or out-of-range spans instead of garbling the text", () => {
    const bad = [MARKS[0], { ...MARKS[1], start: MARKS[0].start + 3 }, { ...MARKS[2], end: NOTE.length + 5 }];
    expect(render(bad).replace(/<[^>]+>/g, "")).toBe(NOTE);
  });

  it("legend names every state in words, not colour alone", () => {
    const html = text(<CitationLegend />);
    for (const w of ["Potential conflict", "Not found in the records available to you", "Status not confirmed"]) expect(html).toContain(w);
  });

  it("the viewer opens with a download and close, before anything loads", () => {
    const html = text(<DocumentViewer api={createApi("U01")} canonicalId="AP-FIN01-GOMS-88-2022" onClose={() => {}} />);
    expect(html).toContain("AP-FIN01-GOMS-88-2022");
    expect(html).toContain("Download");
    expect(html).toContain("Opening…");
  });

  it("flag sources become links when the page can open documents", () => {
    const html = text(
      <AssistPanel api={createApi("U01")} computerNo="2894562" report={REPORT} onReport={() => {}} onInserted={() => {}} onOpenDoc={() => {}} />,
    );
    expect(html).toMatch(/<button[^>]*class="doclink"[^>]*>AP-FIN01-GOMS-31-2025<\/button>/);
  });
});

describe("OCR review screen (plan §4.2)", () => {
  it("opens on the queue and explains that nothing is indexed until confirmed", () => {
    const html = text(<OcrReview api={createApi("U03")} />);
    expect(html).toContain("Loading the review queue");
  });
  it("is reachable from the menu", () => {
    const html = text(<SideNav view={{ kind: "review" }} go={() => {}} monitoring={false} />);
    expect(html).toMatch(/<button class="on"[^>]*>(?:(?!<\/button>).)*>OCR review<\/span>/);
  });

  it("a conversation turn shows each statement's source, review section, withheld count and notices", () => {
    const turn = {
      session_id: "a".repeat(32), turn: 2, from_cache: false, used_earlier_turn: true, request_id: "r9",
      status: "answered", removed: 2, message: null, documents: ["AP-FIN01-GOMS-88-2022"],
      notices: ["Some text in AP-FIN01-GOMS-901-2026 is addressed to an AI system rather than to officers."],
      as_of: "2026-10-02", first_cut: null,
      statements: [
        { text: "On 02-10-2026 the order records show AP-FIN01-GOMS-88-2022 as superseded.", quote: null,
          source: "order records",
          citations: [{ evidence_id: "", canonical_id: "AP-FIN01-GOMS-88-2022", doc_type: "Government Order", status: "superseded", page: null }] },
        { text: "Among the records you may see, 2 spouse ground transfer matters were approved (of 3 decided).",
          quote: null, source: "file records",
          citations: [{ evidence_id: "", canonical_id: "AP-USD01-NOTE-USD0112-44-2025", doc_type: "Noting", status: "approved", page: null }] },
        { text: "1 record(s) name S. Madhavi: Noting in File No.USD01-12/31/2022-ESTT.I.", quote: null,
          source: "entity records",
          citations: [{ evidence_id: "", canonical_id: "AP-USD01-NOTE-USD0112-31-2022", doc_type: "Noting", status: "", page: null }] },
        { text: "Urban Services (USD01): AP-USD01-NOTE-USD0112-31-2022 cites G.O.Ms.No.88.", quote: null,
          source: "link records",
          citations: [{ evidence_id: "", canonical_id: "AP-USD01-NOTE-USD0112-31-2022", doc_type: "Noting", status: "", page: null }] },
        { text: "Under the older order, spouse cases were exempt.", quote: null, source: "evidence",
          confidence: { band: "low", score: 0.3, factors: [
            { name: "retrieval", value: 1, reason: "Found by its exact reference" },
            { name: "validity", value: 0.3, reason: "Cited order is superseded on 02-10-2026" } ] },
          citations: [{ evidence_id: "EV-1", canonical_id: "AP-FIN01-GOMS-88-2022", doc_type: "G.O.", status: "superseded", page: null }] },
        { text: "Spouse cases are given preference.", quote: "shall be given preference", source: "evidence",
          citations: [{ evidence_id: "EV-1", canonical_id: "AP-FIN01-GOMS-31-2025", doc_type: "Government Order", status: "in force", page: 1 }] },
      ],
      review_needed: [
        { text: "The ceiling may be relaxed.", quote: null, source: "evidence",
          citations: [{ evidence_id: "EV-2", canonical_id: "AP-FIN01-GOMS-31-2025", doc_type: "Government Order", status: "in force", page: 1 }] },
      ],
    } as unknown as ChatTurn;
    const html = text(<ChatReply asked="Is that order still in force?" reply={turn} />);
    expect(html).toContain("From the order records: ");
    expect(html).toContain("Counted from the file records you may see: ");
    // one row per record under "Sources": a record cited twice (entity + link) is listed once
    expect(html).toContain("Sources (4)");
    expect(html).toContain("From the records that name them: ");
    expect(html).toContain("Low confidence: check before relying on it");
    // the weakest reason comes first
    expect(html.indexOf("Cited order is superseded")).toBeLessThan(html.indexOf("Found by its exact reference"));
    expect(html).toContain("Source: ");
    expect(html).toContain("Review needed");
    expect(html).toContain("2 statement(s) withheld");
    expect(html).toContain("addressed to an AI system");
    expect(html).toContain("re-checked now");
    const none = { ...turn, statements: [], review_needed: [], removed: 0, notices: [], used_earlier_turn: false,
      message: "No sufficiently supported answer was found in the authorised records." } as ChatTurn;
    expect(text(<ChatReply asked="x" reply={none} />)).toContain("No sufficiently supported answer");
    expect(text(<ChatPanel api={createApi("U01")} computerNo="2894562" />)).toContain("Drafts only.");
  });

  it("feedback controls show on an answer, its statements and pre-send flags — only with an api", () => {
    const turn = {
      session_id: "a".repeat(32), turn: 1, from_cache: false, used_earlier_turn: false, request_id: "r9",
      status: "answered", removed: 0, message: null, documents: [], notices: [], as_of: "2026-10-02", first_cut: null,
      statements: [{ text: "Spouse cases are given preference.", quote: null, source: "evidence",
        citations: [{ evidence_id: "EV-1", canonical_id: "AP-FIN01-GOMS-31-2025", doc_type: "Government Order", status: "in force", page: 1 }] }],
      review_needed: [],
    } as unknown as ChatTurn;
    const withApi = text(<ChatReply api={createApi("U01")} asked="x" reply={turn} />);
    expect(withApi).toContain("Was this answer useful?");
    expect((withApi.match(/👍/g) ?? []).length).toBe(2); // the answer + its one statement
    expect(text(<ChatReply asked="x" reply={turn} />)).not.toContain("👍");
    const panel = text(
      <AssistPanel api={createApi("U01")} computerNo="2894562" report={REPORT} onReport={() => {}} onInserted={() => {}} />,
    );
    expect(panel).toContain("Needs review");
    expect(panel).toContain("Set aside");
  });
});


describe("FAQ analytics on the monitoring pad (ADR-0059)", () => {
  const base = {
    request_id: "r", days: 14, since: "2026-11-05", activity: [], frequent: [], officers: [], gaps: [],
    slowest: [], feedback: [], cache: {}, truncated: false,
    overview: { since: "2026-11-05", days: [], questions: 0, outcomes: {}, cache_hit_rate: null, no_answer_rate: null,
      p50_ms: null, p90_ms: null, answered_by: {}, feedback: {}, start: {} },
  };
  it("shows topics, breakdowns and intents in words", () => {
    const html = renderToString(<WhatIsAsked data={{
      ...base,
      topics: [{ word: "transfer", questions: 7, no_answer: 2 }],
      by_department: [{ name: "USD01 · ESTT.I", questions: 7, answered: 5, no_answer: 2, reasked: 1, avg_ms: 900 }],
      by_role: [], by_intent: [{ name: "precedent_lookup", questions: 7, answered: 5, no_answer: 2, reasked: 0, avg_ms: 900 }],
    } as never} />);
    expect(html).toContain("transfer");
    expect(html).toContain("USD01 · ESTT.I");
    expect(html).toContain("Precedent lookup");
    expect(html).toContain("No questions in this window."); // by role, empty
  });
  it("lists a reworded question once with its wordings and re-asks", () => {
    const html = renderToString(<Questions empty="none" rows={[{ question: "Has a spouse transfer been decided?",
      withheld: false, times: 4, officers: 2, answered_rate: 0.5, avg_ms: 900, last_asked: "2026-11-18T09:00:00Z",
      variants: 3, reasked: 1, intent: "precedent_lookup" }]} />);
    expect(html).toContain("3<!-- --> wordings");
    expect(html).toContain("re-asked <!-- -->1<!-- -->×");
  });
});

describe("assistant-style answers (ADR-0067)", () => {
  it("a composed answer leads with the direct line and shows every checked statement under its heading", () => {
    const c = (id: string) => ({ evidence_id: "EV", canonical_id: id, doc_type: "G.O.", status: "in force", page: 1 });
    const turn = {
      session_id: "a".repeat(32), turn: 1, from_cache: false, used_earlier_turn: false, request_id: "r1",
      status: "answered", removed: 0, message: null, documents: [], notices: [], as_of: "2026-11-24", first_cut: null,
      review_needed: [],
      statements: [
        { text: "G.O.Ms.No.31 is in force.", quote: null, source: "evidence", citations: [c("AP-FIN01-GOMS-31-2025")] },
        { text: "G.O.Ms.No.88 was superseded.", quote: null, source: "evidence", citations: [c("AP-FIN01-GOMS-88-2022")] },
      ],
      composed: { lead: "G.O.Ms.No.31 now governs transfers.", lead_uses: [1],
        sections: [{ heading: "Current position", items: [1] }, { heading: "Earlier orders", items: [2] }] },
    } as unknown as ChatTurn;
    const html = text(<ChatReply asked="which order applies?" reply={turn} />);
    expect(html).toContain("G.O.Ms.No.31 now governs transfers.");
    expect(html.indexOf("Current position")).toBeLessThan(html.indexOf("Earlier orders"));
    expect(html).toContain("G.O.Ms.No.88 was superseded.");
    expect(html).toContain("Sources (2)");
  });
});

describe("file summary in the chat (ADR-0067 addendum)", () => {
  it("shows the written summary with its notes, the notes in full folded under it", async () => {
    const { fileTools } = await import("./components/FileChatTools");
    const s = {
      request_id: "r", computer_no: "1", file_no: "USD01-31/4/2025-VIG", chain: [], last_direction: 3, gaps: [],
      gap_message: null, pending_documents: 1, pending_message: "1 more document(s) wait for text review.",
      notes: [{ note_no: 1, paragraphs: null, post: "Section Officer (Vigilance)", signed_at: "2025-04-09T10:00:00", text: "A complaint has been received.", source: "AP-X" }],
      summary: { lead: "A complaint was received and an enquiry approved.", lead_notes: [1, 3],
        points: [{ text: "A complaint has been received.", notes: [1] }] },
    };
    const api = { fileSummary: async () => s } as unknown as Parameters<typeof fileTools>[0]["api"];
    const tool = fileTools({ api, computerNo: "1", onInserted: () => undefined, onOpenDoc: () => undefined, records: () => null })
      .find((t) => t.id === "summary");
    const html = text(<>{await tool?.run("Summarise this file")}</>);
    expect(html).toContain("A complaint was received and an enquiry approved.");
    expect(html).toContain("#3");
    expect(html).toContain("The notes in full (1)");
  });
});

describe("conflicts between the records an answer used (owner, 25 Nov 2026)", () => {
  it("shows a type G flag as advisory, never as a resolution", () => {
    const turn = {
      session_id: "a".repeat(32), turn: 1, from_cache: false, used_earlier_turn: false, request_id: "r1",
      status: "answered", removed: 0, message: null, documents: [], notices: [], as_of: "2026-11-25", first_cut: null,
      review_needed: [], statements: [],
      conflicts: [{ type: "G", cited: "AP-USD01-CIRMEMO-USD01WRKS0-9-2023", certain: false,
        evidence_ids: ["AP-USD01-CIRMEMO-USD01WRKS0-9-2023", "AP-USD01-GOMS-27-2024"],
        explanation: "Potential conflict — the circular says Rs.1.50 crore, while the higher-level G.O. says Rs.1.00 crore on the same point. … review recommended." }],
      conflict_check: "done",
    } as unknown as ChatTurn;
    const html = text(<ChatReply asked="Is Circular Memo No.9/2023 still valid?" reply={turn} />);
    expect(html).toContain("Hierarchy (G)");
    expect(html).toContain("Rs.1.50 crore");
    expect(html).toContain("nothing has been decided for you");
  });
});
