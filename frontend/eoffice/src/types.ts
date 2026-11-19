// Shapes returned by the sandbox and assist API (backend/app/eoffice_mock/routes.py,
// backend/app/agents/routes.py). SYNTHETIC sandbox data only.

export interface Profile {
  user_id: string; name: string; post: string; department?: string; section?: string | null; clearance?: string;
}

export interface Me extends Profile {
  banner: string; department: string; section: string | null; clearance: string;
  search_scopes: string[];
}

export interface FileRow {
  computer_no: string; file_no: string; subject: string; department: string;
  dealing_section: string; category: string; classification: string; state: string;
  // e-Office folders (Inbox / Created / Closed) — present in the file listing
  with_me?: boolean; created_by_me?: boolean; holder_post?: string | null; sent_by_post?: string | null;
  received_on?: string | null; due_on?: string | null; priority?: string; created_on?: string | null;
}

export interface Note {
  note_id: string; note_no: number; paragraph_from: number; state: "yellow" | "green";
  author_post: string; text_source: "native" | "needs_ocr"; text: string | null;
  versions: number; created_by_assistant: boolean;
}

export interface DraftRow {
  draft_id: string; kind: string; status: string; text: string | null; request_id: string | null;
  versions: number;
}

/** Feedback (plan §9.2, ADR-0031): IDs and fixed codes only — never text. */
export type FeedbackKind = "answer" | "statement" | "conflict_flag";
export type FeedbackAction = "thumbs_up" | "thumbs_down" | "accepted" | "dismissed";
export type FeedbackReason =
  | "wrong_source" | "not_relevant" | "outdated" | "incomplete" | "not_applicable" | "already_handled" | "other";
export interface FeedbackIn {
  kind: FeedbackKind; request_id: string; action: FeedbackAction;
  session_id?: string; canonical_id?: string; computer_no?: string; flag_type?: Flag["type"];
  reason?: FeedbackReason;
}

export interface Correspondence {
  correspondence_id: string; kind: "puc" | "fr"; page_from: number; page_to: number;
  title: string; canonical_id: string | null;
}

export interface Movement {
  seq: number; from_user: string; to_user: string; sent_at: string; remarks: string;
  priority: string; sent_back: boolean; from_post?: string | null; to_post?: string | null; due_on?: string | null;
}

export interface FilePage {
  banner: string;
  file: FileRow & { previous_references: string[]; later_references: string[]; linked_files: string[] };
  notes: Note[]; drafts: DraftRow[]; correspondence: Correspondence[]; movements: Movement[];
  submitted?: DfaRow[]; awaiting_approval?: DfaRow[]; attachments?: AttachmentRow[];
}

/** A DFA on its way to issue (ADR-0045). */
export interface DfaRow {
  draft_id: string; kind: string; status: "submitted" | "dispatched" | string; text: string | null;
  submitted_at: string | null; author_post: string | null; approved_by_post: string | null; issued_as: string | null;
}
export interface AttachmentRow { attachment_id: string; filename: string; size: number; uploaded_by_post: string | null; uploaded_at: string }

/** What of a file is in institutional memory, and what is still waiting (ADR-0045). */
export interface FileRecords {
  request_id: string; computer_no: string; file_no: string;
  records: { canonical_id: string; doc_type: string; subject: string; issue_date: string | null;
    standing: Standing; use_instead: string | null; versions: number; last_event: string | null }[];
  waiting: { filename: string; waiting_for: string[] }[];
}

/** The draft workspace the server keeps (ADR-0046): the officer's own choices and words only. */
export interface DraftWorkspace {
  format_id: string | null; inputs: Record<string, string>; suggest: boolean;
  added: string[]; dropped: string[]; previous_references: string[]; prepared: boolean; text: string;
}

export interface Flag {
  type: "A" | "B" | "C" | "D" | "E" | "F" | "G"; cited: string; evidence_ids: string[];
  explanation: string; certain: boolean; review_state: string;
}

interface AssistMeta { request_id: string; calibrated: boolean; mock_rules: boolean }

export interface PresendReport extends AssistMeta {
  note_id?: string; outcome: "conflicts_found" | "review_needed" | "clear"; flags?: Flag[];
  status_unconfirmed?: string[]; awaiting_review?: string[]; fact_gaps?: string[]; authority_message?: string | null;
  message?: string;
}

export interface DocOut {
  canonical_id: string; doc_type: string; subject: string; issue_date: string | null;
  file_no: string | null;
}

export interface SearchResult extends AssistMeta {
  documents: DocOut[]; files: string[]; ladder_level: string | null;
}

export interface ReferenceResult extends AssistMeta {
  found: boolean; documents?: DocOut[]; status?: string | null; by?: string | null;
  current_version?: string | null; message?: string | null; choices?: string[];
  since?: string | null; paragraph?: string | null;
  cited_clause?: ClauseText | null; successor_clause?: ClauseText | null;
  successor_is_current?: boolean; clause_note?: string | null;
}

/** Touchpoint 14: the deterministic parts of a draft for approval (no model text). */
export interface DfaReadItem {
  canonical_id: string; doc_type: string; subject: string; issue_date: string | null;
  in_place_of: string[]; cited_in_note: boolean; status_confirmed: boolean;
}

export interface DfaPreview extends AssistMeta {
  computer_no: string; file_no: string; draft_note: string | null; abstract: string;
  read_list: DfaReadItem[]; left_out: { cited: string; reason: string }[];
  flags: Flag[]; caveats: string[]; body: string; citations: string[]; order_paragraphs: string;
}

/** Touchpoint 6: cited points for a Yellow Note (no model text). */
export interface CitedPoint { topic: string; clause_id: string; text: string }
export interface PrecedentDecision {
  file_no: string; source: string; note_no: number; paragraph: number | null; decided_on: string | null;
  decision: string; windows: string[]; in_window: boolean | null;
}
export interface FirstCut extends AssistMeta {
  computer_no: string; file_no: string; draft_note: string | null; ground: string | null;
  orders: DfaReadItem[]; left_out: { cited: string; reason: string }[]; points: CitedPoint[];
  precedents: PrecedentDecision[]; flags: Flag[]; body: string; citations: string[]; note_text: string;
}

/** A paragraph of an order, with its clause-level ID (touchpoint 10). */
export interface ClauseText { clause_id: string; text: string }

export interface SoFarNote {
  note_no: number; paragraphs: [number, number] | null; post: string | null;
  signed_at: string | null; text: string; source: string;
}

export interface FileSoFar extends AssistMeta {
  computer_no: string; file_no: string; notes: SoFarNote[]; chain: string[];
  last_direction: number | null; gaps: [number, number][]; gap_message: string | null;
  pending_documents: number; pending_message: string | null;
}

export interface LinkSuggestion { file_no: string; rank: number; documents: DocOut[] }

export interface LinkSuggestions extends AssistMeta {
  computer_no: string; suggestions: LinkSuggestion[]; message: string | null;
}

/** Touchpoint 7: a previous note paragraph or correspondence page of the same file. */
export interface NoteReferenceSuggestion {
  kind: "previous_note" | "correspondence_page"; target_id: string;
  note_no: number | null; paragraph: number | null; page_from: number | null; page_to: number | null;
  text: string; source: string | null; matched_terms: string[]; insert_text: string;
}

export interface NoteReferences extends AssistMeta {
  computer_no: string; matched_by: "explicit" | "keywords" | "none";
  suggestions: NoteReferenceSuggestion[]; message: string | null; matching: string;
}

export interface ReceiptRow {
  computer_no: string; receipt_no: string; diary_date: string; sender: string;
  letter_ref: string | null; letter_date: string | null; main_category: string; subject: string;
  dealing_section: string; put_in_file: string | null; letter_pending: boolean;
}

export interface NoticeDoc { canonical_id: string; doc_type: string | null; subject: string | null; issue_date: string | null }

export interface Notice {
  new: NoticeDoc; changed: NoticeDoc; change: "SUPERSEDES" | "REPEALS" | "AMENDS";
  files: { file_no: string; citing_doc: string }[];
}

export interface Notices extends AssistMeta { notices: Notice[] }

export interface ReceiptFlag extends Flag { about: "this order" | "cited order" }

export interface ReceiptReview extends AssistMeta {
  computer_no: string; as_of: string; document: DocOut | null; summary: string[]; cited: string[];
  flags: ReceiptFlag[]; status_unconfirmed: string[];
  put_in: { suggestion: "existing_file" | "new_file" | "no_assistance"; files: string[]; related_files: string[] };
  message: string | null;
}

export interface GoverningOrder {
  cited: string; found: boolean; status: string | null; by: string | null;
  current_version: string | null; message: string | null;
}

export interface Brief extends AssistMeta {
  computer_no: string; file_no: string; subject: string; draft_id: string | null;
  proposal: {
    action: string | null; post_level: string | null; amount_rupees: number | null;
    proposed_authority: string | null; proposal_date: string | null;
    evidence: Record<string, string>; not_stated: string[];
  };
  chain: string[]; put_up: { post: string | null; signed_at: string | null; source: string } | null;
  governing: GoverningOrder[];
  presend: PresendReport | null;
  precedents: { file_no: string; documents: DocOut[] }[];
  movement: string[];
}

export interface DraftReceipt {
  request_id: string; draft_id: string; kind: string; computer_no: string; status: string;
}

// Citation highlights (ADR-0015) and document preview (ADR-0014).
export type HighlightState = "conflict" | "review" | "unconfirmed" | "not_found" | "ok" | "file";

export interface Highlight {
  start: number; end: number; raw: string; kind: "order" | "efile"; state: HighlightState;
  canonical_id: string | null; file_no: string | null; flags: Flag[];
}

export interface Highlights extends AssistMeta {
  computer_no: string; as_of: string; notes: { note_id: string; highlights: Highlight[] }[];
}

export interface DocumentInfo {
  request_id: string; canonical_id: string; doc_type: string; subject: string; issue_date: string | null;
  version: string; media_type: string; previewable: boolean; filename: string;
  standing?: Standing; use_instead?: string | null;
  history?: { version: string; received_at: string; event: string }[];
}

// OCR review (plan §4.2): scans waiting for a reviewer.
export interface OcrPageInfo { page: number; confidence: number | null; languages: string[] }
export interface OcrReviewItem {
  item_id: string; created_at: string; reason: string; filename: string; department: string;
  section: string; classification: string; file_no: string | null; engine: string | null; pages: OcrPageInfo[];
}
export interface OcrReviewDetail extends OcrReviewItem {
  request_id: string; media_type: string; previewable: boolean; draft_text: string; has_draft: boolean;
}
export interface OcrReviewResult {
  request_id: string; status: "indexed" | "held" | "rejected"; canonical_id?: string | null;
  corrected?: boolean; still_held_for?: { kind: string; reason: string }[];
}

/** One statement of a conversational answer (ADR-0024, ADR-0029). */
export interface ChatCitation {
  evidence_id: string; canonical_id: string; doc_type: string; status: string; page: number | null;
  issue_date?: string | null;
  /** As an officer writes it in a note, e.g. "G.O.Ms.No.31, Finance Department, dated 12-05-2025, para 2(v)". */
  reference?: string;
}
export interface ChatStatement {
  text: string; quote: string | null; citations: ChatCitation[];
  // "file records": a count of decided files the officer may see, no model involved (ADR-0051)
  // "link records": records of other departments linked to the order, from the graph (ADR-0056)
  // "entity records": the records naming a person or office the question names (ADR-0058)
  source: "evidence" | "order records" | "file records" | "link records" | "entity records";
  // how far it can be relied on, from facts the system holds (ADR-0054); absent on older answers
  confidence?: Confidence | null;
}
export interface Confidence {
  band: "high" | "medium" | "low"; score: number;
  factors: { name: string; value: number; reason: string }[];
}
export interface NoteLine { text: string; refs: string[] }
export interface DraftNote { sections: { heading: string; lines: NoteLine[] }[]; removed: number; text: string; engine: string | null }

/** POST /assist/chat (ADR-0029): one turn of the conversation. */
export interface ChatTurn extends AssistMeta {
  session_id: string; turn: number; from_cache: boolean; used_earlier_turn: boolean;
  request_id: string;
  status: "answered" | "review_needed" | "no_answer" | "not_run" | "denied";
  statements: ChatStatement[]; review_needed: ChatStatement[]; removed: number;
  message: string | null; documents: string[]; notices: string[]; as_of: string;
  first_cut: (FirstCut & { note: DraftNote | null }) | null;
}

/** Streamed turn (ADR-0033): progress, then statements that already passed the citation check,
 *  then `done` with the full answer, which replaces what was streamed. */
export type ChatStage = "searching" | "found" | "writing" | "checking";
export type ChatEvent =
  | { type: "stage"; stage: ChatStage; records?: number; rung?: string | null }
  | { type: "statement" | "review"; statement: ChatStatement }
  | { type: "done"; answer: ChatTurn }
  | { type: "error"; message: string };

/** The cited paragraph for the hover preview (ADR-0034). */
export interface PassageContext {
  request_id: string; canonical_id: string; reference: string; subject: string;
  paragraph: string | null; highlight: [number, number] | null;
}

/** The officer's digest (ADR-0034). */
export interface DigestWaiting {
  computer_no: string; file_no: string; subject: string; received_on: string | null;
  days_waiting: number | null; due_on: string | null; overdue: boolean; priority: string; sent_back: boolean;
}
export interface DigestChange {
  computer_no: string; file_no: string; cited: string; reference: string; status: string;
  by: string | null; by_reference: string | null; since: string | null; new: boolean;
}
export interface Digest extends AssistMeta {
  as_of: string; window_days: number; waiting: DigestWaiting[]; changed_orders: DigestChange[];
}

/** The monitoring officer's pad (ADR-0035). */
export interface UsageDay {
  day: string; questions: number; answered: number; no_answer: number; cache_hits: number;
  p50_ms: number | null; p90_ms: number | null;
}
export interface UsageOverview {
  since: string; days: UsageDay[]; questions: number; outcomes: Record<string, number>;
  cache_hit_rate: number | null; no_answer_rate: number | null; p50_ms: number | null; p90_ms: number | null;
  answered_by: Record<string, number>; feedback: Record<string, number>;
  start: { built_at?: string; build_seconds?: number; warm_start?: boolean };
}
export interface ActivityRow {
  ts: string; query_id: string; user_id: string; role: string; department: string; section: string | null;
  question: string | null; withheld: boolean; intent: string | null; outcome: string;
  answered_by: string | null; latency_ms: number; cache_hit: boolean; cited: number; feedback: string | null;
  flags?: string[];
}
export interface FrequentQuestion {
  question: string | null; withheld: boolean; times: number; officers: number;
  answered_rate: number; avg_ms: number; last_asked: string;
  /** FAQ analytics (ADR-0059): asks in other words grouped as one question */
  variants?: number; reasked?: number; intent?: string | null;
}
/** Questions by one dimension: department · section, role or intent (plan §10.4; ADR-0059). */
export interface Breakdown {
  name: string; questions: number; answered: number; no_answer: number; reasked: number; avg_ms: number;
}
/** A subject word, counted only from questions this monitoring officer may read. */
export interface Topic { word: string; questions: number; no_answer: number; }
export interface OfficerActivity {
  user_id: string; role: string; department: string; questions: number; answered: number;
  no_answer: number; avg_ms: number; thumbs_up: number; thumbs_down: number; last_seen: string;
}
export interface FeedbackRow {
  ts: string; user_id: string; target: string; action: string; reason: string | null; edit_share: number | null;
}
export interface MonitorData {
  request_id: string; days: number; since: string; overview: UsageOverview;
  activity: ActivityRow[]; frequent: FrequentQuestion[]; officers: OfficerActivity[];
  gaps: FrequentQuestion[]; slowest: ActivityRow[]; feedback: FeedbackRow[];
  cache: Record<string, string | number | boolean | null>; truncated: boolean;
  alerts?: AlertsView | null;
  by_department?: Breakdown[]; by_role?: Breakdown[]; by_intent?: Breakdown[];
  topics?: Topic[]; reasked?: number;
}

/** Unusual-activity alerts (ADR-0036). Codes only; words gated by clearance as on the pad. */
export type Severity = "high" | "medium" | "low";
export interface AlertExample {
  ts: string; query_id: string | null; what: string; question: string | null; withheld: boolean;
}
export interface Alert {
  alert_id: string; rule: string; severity: Severity; title: string; user_id: string; role: string;
  department: string; day: string; first_seen: string; last_seen: string; count: number;
  examples: AlertExample[]; status: "open" | "reviewed" | "escalated";
  reviewed_by: string | null; reviewed_at: string | null;
}
export interface DepartmentAlerts {
  department: string; high: number; medium: number; low: number; open: number; officers: number;
}
export interface AlertsView {
  config_version: string; config_status: string; alerts: Alert[];
  by_department: DepartmentAlerts[]; by_rule: Record<string, number>;
}

/** Extended touchpoints 12, 17, 19 (ADR-0037). */
export interface PutUp { note_no: number; post: string | null; signed_at: string | null; excerpt: string; source: string }
export interface MovementStep {
  seq: number; from_user: string; from_post: string | null; to_user: string; to_post: string | null;
  sent_at: string; due_on: string | null; priority: string; remarks: string; sent_back: boolean;
  days_held: number | null; notes: PutUp[];
}
export interface Movements extends AssistMeta {
  computer_no: string; subject: string; file_no: string; state: string; steps: MovementStep[];
  pending_with: string | null; pending_with_post: string | null; pending_since: string | null;
  days_pending: number | null; due_on: string | null; overdue: boolean; sent_back_times: number;
  headline: string; last_direction: PutUp | null;
}
export interface OrderChange {
  cited: string; cited_reference: string; change: string; by: string | null; by_reference: string | null;
  by_subject: string | null; on: string | null; current_version: string | null; after_decision: boolean | null;
}
export interface SinceDecision extends AssistMeta {
  computer_no: string; subject: string; file_no: string; state: string; decided: PutUp | null;
  decided_on: string | null; relied_on: string[]; changes: OrderChange[]; unchanged: string[]; headline: string;
}
export interface FileInHand {
  computer_no: string; file_no: string; subject: string; pending_with: string | null; pending_with_post: string | null;
  since: string | null; days_pending: number | null; due_on: string | null; overdue: boolean; sent_back: boolean;
  last_direction: PutUp | null; changed_orders: number;
}
export interface SectionOrder {
  canonical_id: string; reference: string; subject: string | null; status: string; by: string | null;
  by_reference: string | null; since: string | null; files: string[];
}
export interface Handover extends AssistMeta {
  section: string | null; message?: string; department?: string; as_of?: string; open_files?: number;
  closed_files?: number; in_hand?: FileInHand[]; standing?: SectionOrder[]; no_longer_in_force?: SectionOrder[];
  decisions?: { computer_no: string; file_no: string; subject: string; decided: PutUp }[]; headline?: string;
}

/** Extended touchpoints 1, 5, 16 (ADR-0038). */
export interface PrefillField { value: string | null; read_from: string | null }
export interface DiaryPrefill {
  letter_ref: PrefillField; letter_date: PrefillField; sender: PrefillField; main_category: PrefillField;
  subject: PrefillField; department: string | null; from_ocr: boolean; ocr_confidence: number | null; missing: string[];
}
export interface Diarise extends AssistMeta { computer_no: string; prefill: DiaryPrefill | null; message: string | null }
export interface PreviousRefs extends AssistMeta {
  suggestions: { file_no: string; computer_no: string; rank: number; documents: { canonical_id: string; subject: string | null }[] }[];
  message: string | null;
}
export interface ClosingRemarks extends AssistMeta {
  computer_no: string; file_no: string; text: string | null; cited: string[]; blockers: string[]; can_close: boolean;
}


/** The officer's own display and assistant settings (ADR-0041). Never access. */
export interface Preferences {
  theme: "light" | "dark" | "system";
  text_size: "normal" | "large" | "larger";
  density: "comfortable" | "compact";
  contrast: "standard" | "high";
  reduce_motion: boolean;
  date_style: "dd-mm-yyyy" | "dd Mon yyyy";
  note_font: "serif" | "sans";
  landing: "inbox" | "receipts" | "search" | "monitor";
  due_soon_days: number;
  assistant_panel: "open" | "collapsed";
  stream_answers: boolean;
  shortcuts: boolean;
  show_notices: boolean;
}

export const DEFAULT_PREFERENCES: Preferences = {
  theme: "light", text_size: "normal", density: "comfortable", contrast: "standard", reduce_motion: false,
  date_style: "dd-mm-yyyy", note_font: "serif", landing: "inbox", due_soon_days: 3,
  assistant_panel: "open", stream_answers: true, shortcuts: true, show_notices: true,
};

/* ---- Draft workspace (ADR-0044) ---- */
export type InputName = "subject" | "request" | "facts" | "proposal" | "signatory" | "addressees" | "copy_to";
export interface DraftFormat {
  id: string; family: "noting" | "outgoing"; kind: "note" | "go" | "memo" | "letter";
  title: string; use_when: string; saves_as: "yellow_note" | "dfa_draft"; basis: string;
  inputs: InputName[]; skeleton: string; number_label: string | null;
}
export interface DraftFormats { version: number; status: "mock" | "confirmed"; formats: DraftFormat[] }
export type DraftInputs = Partial<Record<InputName, string>>;
export interface DraftPart { key: string; text: string; origin: "officer" | "record" | "check" | "fixed" | "blank"; refs: string[] }
export interface DraftReadItem {
  canonical_id: string; label: string; doc_type: string; subject: string; issue_date: string | null;
  in_place_of: string[]; cited_in_note: boolean; status_confirmed: boolean;
}
export interface DraftRelation { kind: string; direction: "out" | "in"; other: string; other_subject: string; other_label: string }
export type Standing = "in_force" | "superseded" | "repealed" | "expired" | "not_yet_in_force" | "unconfirmed" | "not_an_order";
export interface CloseMatch {
  canonical_id: string; label: string; doc_type: string; subject: string; issue_date: string | null;
  file_no: string | null; found_by: string; standing: Standing; use_instead: string | null;
  relations: DraftRelation[]; in_read_list: boolean; flagged: string[];
}
export interface DraftFlag { type: string; cited: string; evidence_ids: string[]; explanation: string; certain: boolean; review_state: string }
export interface PreparedDraft {
  request_id: string; computer_no: string | null; format: DraftFormat;
  draft: { format_id: string; saves_as: "yellow_note" | "dfa_draft"; parts: DraftPart[]; text: string; citations: string[]; placeholders: number };
  read_list: DraftReadItem[]; left_out: { cited: string; reason: string }[];
  checks: { outcome: string; flags: DraftFlag[]; status_unconfirmed: string[]; awaiting_review: string[]; fact_gaps: string[]; authority_message: string | null };
  /** unavailable: rungs whose store failed this time (plan §14.4), e.g. ["L3"] */
  matches: { ladder: string; documents: CloseMatch[]; unavailable?: string[] };
  suggested: null | {
    lines: { text: string; refs: string[]; heading: string | null }[];
    removed: number; engine: string | null; fallback: boolean; reason: string | null;
    /** today's suggested-wording requests for this officer, counted on the server (ADR-0060) */
    usage?: { used: number; limit: number } | null;
  };
  calibrated: boolean; mock_rules: boolean;
  /** earlier files on the subject the officer can open: Previous References for a new matter;
   * for an open file, its own previous references first, then similar files (ADR-0060) */
  related_files?: { file_no: string; computer_no: string }[];
  /** the history of each order read, and the people the matter names, within access (ADR-0060) */
  context?: DraftContext;
}
export interface DraftContext {
  histories: { order: string; lines: { text: string; refs: string[] }[]; in_force: string[]; status_reportable: boolean }[];
  people: { name: string; role: string | null; officer_id: string | null; records: [string, string][] }[];
}
