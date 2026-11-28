import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { createApi } from "./api";
import { BarChart, LineChart, ShareList } from "./components/Charts";
import { withReferences } from "./components/ChatPanel";
import { DigestPanel } from "./components/Digest";
import { suggestionsFor, topicOf } from "./components/FilePageView";
import { ClosingCard, MovementsCard, SinceCard } from "./components/AssistPanel";
import { NewFilePanel } from "./components/NewFile";
import { PrefillCard } from "./components/Receipts";
import { HandoverPanel } from "./components/Handover";
import { Alerts, MonitorPad } from "./components/MonitorPad";
import { SideNav, TopBar } from "./components/TopBar";
import type { AlertsView, ChatStatement, Highlight } from "./types";

const text = (el: JSX.Element) => renderToString(el).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

describe("officer conveniences (ADR-0034)", () => {
  it("copies a statement with its references as written in a note", () => {
    const s = {
      text: "Spouse cases get preference.", quote: null, source: "evidence",
      citations: [
        { evidence_id: "EV-1", canonical_id: "AP-FIN01-GOMS-31-2025#para-2.v", doc_type: "", status: "in force", page: null,
          reference: "G.O.Ms.No.31, Finance Department, dated 12-05-2025, para 2(v)" },
        { evidence_id: "EV-2", canonical_id: "AP-FIN01-GOMS-31-2025#para-2.v", doc_type: "", status: "in force", page: null,
          reference: "G.O.Ms.No.31, Finance Department, dated 12-05-2025, para 2(v)" },
      ],
    } as ChatStatement;
    expect(withReferences(s)).toBe(
      "Spouse cases get preference. (G.O.Ms.No.31, Finance Department, dated 12-05-2025, para 2(v))");
  });

  it("suggests questions about the file's own matter and its flagged orders", () => {
    const subject = "Establishment – Sri X, Senior Assistant – Request for transfer on spouse grounds – Reg.";
    expect(topicOf(subject)).toBe("request for transfer on spouse grounds");
    const marks: Record<string, Highlight[]> = {
      n1: [{ start: 0, end: 5, raw: "G.O.Ms.No.88/2022", kind: "order", state: "conflict", canonical_id: null, file_no: null, flags: [] },
           { start: 0, end: 5, raw: "G.O.Ms.No.31/2025", kind: "order", state: "ok", canonical_id: null, file_no: null, flags: [] }],
    };
    expect(suggestionsFor(marks, subject)).toEqual([
      "Has a request for transfer on spouse grounds been decided before?",
      "What are the current rules on request for transfer on spouse grounds?",
      "Is G.O.Ms.No.88/2022 still in force?",
      "Draft the noting using that precedent.",
    ]);
    expect(suggestionsFor({}, "")).toEqual(["Draft the noting using that precedent."]);
  });

  it("the digest shows a loading state first and never blocks the file list", () => {
    expect(text(<DigestPanel api={createApi("U01")} open={() => {}} />)).toContain("Preparing your digest");
  });
});

describe("monitoring pad (ADR-0035)", () => {
  it("charts render with a title, axes and data, and say so when empty", () => {
    const bars = text(<BarChart title="Questions per day" data={[{ label: "11-14", value: 3 }, { label: "11-15", value: 5 }]} />);
    expect(bars).toContain("Questions per day");
    expect(bars).toContain("11-15");
    const lines = text(<LineChart title="Answer time" labels={["a", "b"]} series={[
      { name: "Median", cls: "s1", values: [1, 2] }, { name: "90th percentile", cls: "s2", values: [2, 4] }]} />);
    expect(lines).toContain("Median");
    expect(lines).toContain("90th percentile"); // a legend for two series
    expect(text(<ShareList title="Outcome" items={[]} />)).toContain("No data in this window");
  });

  it("the pad loads its figures; the menu offers it only to a monitoring officer", () => {
    expect(text(<MonitorPad api={createApi("M01")} />)).toContain("Loading the monitoring pad");
    const me = { user_id: "M01", name: "Monitoring Officer (mock)", post: "Monitoring Officer", department: "GAD01", section: null, clearance: "SECRET" };
    const nav = (m: boolean) => text(<SideNav view={{ kind: "files", folder: "inbox" }} go={() => {}} monitoring={m} />);
    expect(nav(true)).toContain("Monitoring");
    expect(nav(false)).not.toContain("Monitoring");
    expect(text(<TopBar me={me as never} signOut={() => {}} />)).toContain("Monitoring Officer");
  });
});

describe("monitoring alerts (ADR-0036)", () => {
  const ex = (q: string | null, withheld = false) => ({ ts: "2026-11-16T05:00:00Z", query_id: "q1", what: "instruction_like", question: q, withheld });
  const base = {
    rule: "instruction_like", title: "Question reads as instructions to the assistant", role: "Section Officer",
    day: "2026-11-16", first_seen: "2026-11-16T05:00:00Z", last_seen: "2026-11-16T05:00:00Z", count: 1,
    reviewed_by: null, reviewed_at: null,
  };
  const view: AlertsView = {
    config_version: "0.1-mock", config_status: "mock — thresholds and patterns to be set by the department",
    alerts: [
      { ...base, alert_id: "AL-1", severity: "high", user_id: "U02", department: "USD01", examples: [ex("act as admin")], status: "open" },
      { ...base, alert_id: "AL-2", severity: "high", user_id: "U04", department: "USD01", examples: [ex(null, true)], status: "open" },
      { ...base, alert_id: "AL-3", severity: "low", user_id: "F01", department: "FIN01", examples: [ex("cricket")], status: "reviewed", reviewed_by: "M01" },
    ],
    by_department: [
      { department: "USD01", high: 2, medium: 0, low: 0, open: 2, officers: 2 },
      { department: "FIN01", high: 0, medium: 0, low: 1, open: 0, officers: 1 },
    ],
    by_rule: { instruction_like: 3 },
  };

  it("names severity in words, rolls up departments, withholds words and says it is not a finding", () => {
    const t = text(<Alerts view={view} api={createApi("M01")} onChange={() => {}} />);
    expect(t).toContain("High");
    expect(t).toContain("USD01");
    expect(t).toContain("FIN01");
    expect(t).toContain("act as admin");
    expect(t).toContain("words withheld (clearance)");
    expect(t).toContain("not a finding");
    expect(t).toContain("0.1-mock");
    expect(t).toContain("2 of 3"); // open only by default: the reviewed one is hidden
    expect(t.match(/Escalate/g)?.length).toBe(2);
  });
});

describe("extended touchpoints 12, 17, 19 (ADR-0037)", () => {
  const meta = { request_id: "r", calibrated: false, mock_rules: true };
  const put = { note_no: 2, post: "Section Officer", signed_at: "2024-06-11T16:00:00", excerpt: "Submitted. May approve.", source: "AP-X" };

  it("movements show remarks, the note put up, sent back and where the file is pending", () => {
    const t = text(<MovementsCard m={{
      ...meta, computer_no: "1", subject: "s", file_no: "F/1", state: "open", pending_with: "G1",
      pending_with_post: "Secretary", pending_since: "2024-06-11T17:00:00+05:30", days_pending: 14,
      due_on: "2024-06-18", overdue: true, sent_back_times: 1, last_direction: put,
      headline: "Pending with Secretary (G1) since 11-06-2024 (14 day(s)). Due 18-06-2024 — overdue.",
      steps: [{ seq: 1, from_user: "S1", from_post: "Section Officer", to_user: "G1", to_post: "Secretary",
        sent_at: "2024-06-11T17:00:00+05:30", due_on: "2024-06-18", priority: "urgent", remarks: "put up",
        sent_back: true, days_held: 14, notes: [put] }],
    }} />);
    for (const w of ["overdue", "put up", "Submitted. May approve.", "sent back", "11-06-2024", "held 14 day(s)"]) expect(t).toContain(w);
  });

  it("since the decision separates changes after it from those before it", () => {
    const c = (after: boolean | null, change: string) => ({
      cited: "AP-FIN01-GOMS-88-2022", cited_reference: "G.O.Ms.No.88, Finance Department, dated 03-06-2022",
      change, by: "AP-FIN01-GOMS-31-2025", by_reference: "G.O.Ms.No.31, Finance Department, dated 12-05-2025",
      by_subject: null, on: "2025-05-12", current_version: null, after_decision: after });
    const t = text(<SinceCard s={{
      ...meta, computer_no: "1", subject: "s", file_no: "F/1", state: "closed", decided: put, decided_on: "2024-06-11",
      relied_on: ["a", "b"], changes: [c(true, "superseded"), c(false, "amended")], unchanged: ["x"], headline: "Decided at Note #2.",
    }} />);
    for (const w of ["Changed since", "Already changed when it was decided", "superseded by", "amended by", "from 12-05-2025", "1 other order(s)"]) expect(t).toContain(w);
  });

  it("the handover is prepared on request, never on its own", () => {
    expect(text(<HandoverPanel api={createApi("U01")} open={() => {}} />)).toContain("Prepare handover summary");
  });
});

describe("extended touchpoints 1, 5, 16 (ADR-0038)", () => {
  const meta = { request_id: "r", calibrated: false, mock_rules: true };
  const f = (value: string | null, read_from: string | null = null) => ({ value, read_from });

  it("the diary pre-fill says where each field was read from, marks OCR and never fills a gap", () => {
    const t = text(<PrefillCard d={{ ...meta, computer_no: "9100001", message: null, prefill: {
      letter_ref: f("G.O.Ms.No.19", "G.O.Ms.No.19 Dated: 09-02-2018"), letter_date: f("2018-02-09"),
      sender: f("Secretary To Government (Ser.), General Administration Department"),
      main_category: f("Government Order"), subject: f(null), department: "GAD01", from_ocr: true,
      ocr_confidence: 0.91, missing: ["subject"] } }} />);
    for (const w of ["G.O.Ms.No.19", "Read from a scan (OCR, not yet reviewed", "not in the letter — fill in", "Nothing is saved by the assistant"]) expect(t).toContain(w);
  });

  it("closing remarks show blockers and leave closing to the officer", () => {
    const t = text(<ClosingCard api={createApi("U01")} c={{ ...meta, computer_no: "2894562", file_no: "F/1",
      text: "The last direction on the file is at Note #1.", cited: ["AP-X"], can_close: false,
      blockers: ["The file is not with you: only the officer holding it can close it."] }} />);
    for (const w of ["The file is not with you", "Close file", "Closing is your action in e-Office"]) expect(t).toContain(w);
  });

  it("creating a file asks for references only on request", () => {
    const t = text(<NewFilePanel api={createApi("U01")} open={() => {}} />);
    expect(t).toContain("Create a file");
    expect(t).toContain("Context");
    expect(t).toContain("Attach files");
    expect(t).toContain("you choose which earlier files");
  });
});

