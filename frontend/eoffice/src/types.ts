// Shapes returned by the sandbox and assist API (backend/app/eoffice_mock/routes.py,
// backend/app/agents/routes.py). SYNTHETIC sandbox data only.

export interface Profile { user_id: string; name: string; post: string }

export interface Me extends Profile {
  banner: string; department: string; section: string | null; clearance: string;
  search_scopes: string[];
}

export interface FileRow {
  computer_no: string; file_no: string; subject: string; department: string;
  dealing_section: string; category: string; classification: string; state: string;
}

export interface Note {
  note_id: string; note_no: number; paragraph_from: number; state: "yellow" | "green";
  author_post: string; text_source: "native" | "needs_ocr"; text: string | null;
  versions: number; created_by_assistant: boolean;
}

export interface DraftRow {
  draft_id: string; kind: string; status: string; text: string | null; request_id: string | null;
}

export interface Correspondence {
  correspondence_id: string; kind: "puc" | "fr"; page_from: number; page_to: number;
  title: string; canonical_id: string | null;
}

export interface Movement {
  seq: number; from_user: string; to_user: string; sent_at: string; remarks: string;
  priority: string; sent_back: boolean;
}

export interface FilePage {
  banner: string;
  file: FileRow & { previous_references: string[]; later_references: string[]; linked_files: string[] };
  notes: Note[]; drafts: DraftRow[]; correspondence: Correspondence[]; movements: Movement[];
}

export interface Flag {
  type: "A" | "B" | "C" | "D" | "E" | "F" | "G"; cited: string; evidence_ids: string[];
  explanation: string; certain: boolean; review_state: string;
}

interface AssistMeta { request_id: string; calibrated: boolean; mock_rules: boolean }

export interface PresendReport extends AssistMeta {
  note_id?: string; outcome: "conflicts_found" | "review_needed" | "clear"; flags?: Flag[];
  status_unconfirmed?: string[]; fact_gaps?: string[]; authority_message?: string | null;
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
}

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

export interface DraftReceipt {
  request_id: string; draft_id: string; kind: string; computer_no: string; status: string;
}
