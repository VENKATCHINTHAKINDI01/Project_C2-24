// Thin client for the sandbox + assist API. Sign-in is SIMULATED with a header (sandbox only,
// ADR-0012). Errors keep the server's neutral wording; nothing is retried with less scope.
import type {
  Brief, ChatTurn, DraftWorkspace, FileRecords, ClosingRemarks, Diarise, Handover, Movements, PreviousRefs, SinceDecision, DfaPreview, DocumentInfo, Highlights, OcrReviewDetail, OcrReviewItem, OcrReviewResult, ChatEvent, Digest, DraftReceipt, MonitorData, PassageContext, FeedbackIn, FilePage, FileRow, FileSoFar, FirstCut, LinkSuggestions, Me, Preferences, NoteReferenceSuggestion, NoteReferences, Notices, PresendReport, Profile, ReceiptReview, ReceiptRow, ReferenceResult, SearchResult, DraftFormats, DraftInputs, PreparedDraft } from "./types";

export const SANDBOX_USER_HEADER = "X-Sandbox-User";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

export function headersFor(userId: string | null, json = false): Record<string, string> {
  const h: Record<string, string> = {};
  if (userId) h[SANDBOX_USER_HEADER] = userId;
  if (json) h["Content-Type"] = "application/json";
  return h;
}

export function createApi(userId: string | null, fetchFn: Fetch = (i, init) => fetch(i, init)) {
  async function call<T>(path: string, body?: unknown): Promise<T> {
    const res = await fetchFn(path, {
      method: body === undefined ? "GET" : "POST",
      headers: headersFor(userId, body !== undefined),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) {
      let detail = res.statusText || "Request failed";
      try { detail = ((await res.json()) as { detail?: string }).detail ?? detail; } catch { /* keep */ }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as T;
  }
  /** A stored source file as a Blob, so the sign-in header is sent (no URL carries access). */
  async function blob(path: string): Promise<Blob> {
    const res = await fetchFn(path, { method: "GET", headers: headersFor(userId) });
    if (!res.ok) {
      let detail = res.statusText || "Request failed";
      try { detail = ((await res.json()) as { detail?: string }).detail ?? detail; } catch { /* keep */ }
      throw new ApiError(res.status, detail);
    }
    return res.blob();
  }
  const doc = (cid: string) => `/assist/documents/${encodeURIComponent(cid)}`;
  const approvalPath = (computerNo: string, draftId: string) =>
    `/sandbox/files/${encodeURIComponent(computerNo)}/approvals/${encodeURIComponent(draftId)}`;
  const draftPath = (computerNo: string, draftId: string) =>
    `/sandbox/files/${encodeURIComponent(computerNo)}/drafts/${encodeURIComponent(draftId)}`;
  return {
    ocrQueue: () => call<{ items: OcrReviewItem[] }>("/assist/review/ocr"),
    ocrItem: (itemId: string) => call<OcrReviewDetail>(`/assist/review/ocr/${encodeURIComponent(itemId)}`),
    ocrScan: (itemId: string) => blob(`/assist/review/ocr/${encodeURIComponent(itemId)}/scan`),
    ocrConfirm: (itemId: string, reason: string, correctedText: string | null) =>
      call<OcrReviewResult>(`/assist/review/ocr/${encodeURIComponent(itemId)}/confirm`, { reason, corrected_text: correctedText }),
    ocrReject: (itemId: string, reason: string) =>
      call<OcrReviewResult>(`/assist/review/ocr/${encodeURIComponent(itemId)}/reject`, { reason }),
    highlights: (computerNo: string, notes: { note_id: string; text: string }[]) =>
      call<Highlights>("/assist/highlights", { computer_no: computerNo, notes }),
    documentInfo: (canonicalId: string) => call<DocumentInfo>(doc(canonicalId)),
    documentFile: (canonicalId: string, kind: "preview" | "download") => blob(`${doc(canonicalId)}/${kind}`),
    profiles: () => call<{ banner: string; profiles: Profile[] }>("/sandbox/profiles"),
    me: () => call<Me>("/sandbox/me"),
    preferences: () => call<Preferences>("/sandbox/me/preferences"),
    savePreferences: (p: Preferences) => call<Preferences>("/sandbox/me/preferences", p),
    resetPreferences: () => call<Preferences>("/sandbox/me/preferences/reset", {}),
    files: () => call<{ banner: string; files: FileRow[] }>("/sandbox/files"),
    file: (computerNo: string) => call<FilePage>(`/sandbox/files/${encodeURIComponent(computerNo)}`),
    presend: (computerNo: string) => call<PresendReport>("/assist/presend", { computer_no: computerNo }),
    fileSoFar: (computerNo: string) => call<FileSoFar>("/assist/file-so-far", { computer_no: computerNo }),
    linkSuggestions: (computerNo: string) =>
      call<LinkSuggestions>("/assist/link-suggestions", { computer_no: computerNo }),
    suggestLink: (computerNo: string, fileNo: string, citations: string[], requestId: string) =>
      call<DraftReceipt>("/assist/draft", {
        computer_no: computerNo, kind: "suggested_reference",
        body: `Link file ${fileNo} as a read-only reference (precedent).`, citations, request_id: requestId,
      }),
    noteReference: (computerNo: string, text: string) =>
      call<NoteReferences>("/assist/note-reference", { computer_no: computerNo, text }),
    insertReference: (computerNo: string, s: NoteReferenceSuggestion, requestId: string) =>
      call<DraftReceipt>("/assist/draft", {
        computer_no: computerNo, kind: "suggested_reference",
        body: `Please see ${s.insert_text} (${s.target_id}).`,
        citations: [s.target_id, ...(s.source ? [s.source] : [])], request_id: requestId,
      }),
    receipts: () => call<{ banner: string; receipts: ReceiptRow[] }>("/sandbox/receipts"),
    receipt: (computerNo: string) =>
      call<{ banner: string; receipt: ReceiptRow }>(`/sandbox/receipts/${encodeURIComponent(computerNo)}`),
    receiptAssist: (computerNo: string, asOf?: string) =>
      call<ReceiptReview>("/assist/receipt", asOf ? { computer_no: computerNo, as_of: asOf } : { computer_no: computerNo }),
    notices: () => call<Notices>("/assist/notices"),
    letterArrives: (computerNo: string) =>
      call<{ event_id: string; kind: string }>(`/sandbox/receipts/${encodeURIComponent(computerNo)}/arrive`, {}),
    brief: (computerNo: string) => call<Brief>("/assist/brief", { computer_no: computerNo }),
    movements: (computerNo: string) => call<Movements>("/assist/movements", { computer_no: computerNo }),
    sinceDecision: (computerNo: string) =>
      call<SinceDecision>("/assist/since-decision", { computer_no: computerNo }),
    handover: () => call<Handover>("/assist/handover"),
    diarise: (computerNo: string) => call<Diarise>("/assist/diarise", { computer_no: computerNo }),
    previousRefs: (subject: string) => call<PreviousRefs>("/assist/previous-references", { subject }),
    closingRemarks: (computerNo: string) => call<ClosingRemarks>("/assist/closing-remarks", { computer_no: computerNo }),
    createFile: (subject: string, previousReferences: string[]) =>
      call<{ file: FileRow & { previous_references: string[] } }>("/sandbox/files", { subject, previous_references: previousReferences }),
    closeFile: (computerNo: string, remarks: string) =>
      call<{ file: FileRow }>(`/sandbox/files/${encodeURIComponent(computerNo)}/close`, { remarks }),
    dfa: (computerNo: string) => call<DfaPreview>("/assist/dfa", { computer_no: computerNo }),
    firstCut: (computerNo: string) => call<FirstCut>("/assist/first-cut", { computer_no: computerNo }),
    // Draft workspace (ADR-0044): formats, and a draft prepared from the officer's inputs
    draftFormats: () => call<DraftFormats>("/assist/draft/formats"),
    prepareDraft: (body: {
      computer_no: string | null; format_id: string; inputs: DraftInputs;
      add_references: string[]; drop_references: string[]; suggest: boolean;
    }) => call<PreparedDraft>("/assist/draft/prepare", body),
    createDfa: (computerNo: string, body: string, citations: string[], requestId: string) =>
      call<DraftReceipt>("/assist/draft", {
        computer_no: computerNo, kind: "dfa_draft", body, citations, request_id: requestId,
      }),
    search: (query: string) => call<SearchResult>("/assist/search", { query }),
    chat: (message: string, sessionId: string | null, computerNo?: string) =>
      call<ChatTurn>("/assist/chat", {
        message,
        ...(sessionId ? { session_id: sessionId } : {}),
        ...(computerNo ? { computer_no: computerNo } : {}),
      }),
    /** The same turn as `chat`, streamed (ADR-0033). Resolves with the final answer. */
    chatStream: async (
      message: string, sessionId: string | null, computerNo: string | undefined,
      onEvent: (e: ChatEvent) => void, signal?: AbortSignal,
    ): Promise<ChatTurn> => {
      const res = await fetchFn("/assist/chat/stream", {
        method: "POST",
        signal,
        headers: headersFor(userId, true),
        body: JSON.stringify({
          message,
          ...(sessionId ? { session_id: sessionId } : {}),
          ...(computerNo ? { computer_no: computerNo } : {}),
        }),
      });
      if (!res.ok || !res.body) {
        let detail = res.statusText || "Request failed";
        try { detail = ((await res.json()) as { detail?: string }).detail ?? detail; } catch { /* keep */ }
        throw new ApiError(res.status, detail);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        buf += decoder.decode(value ?? new Uint8Array(), { stream: !done });
        let cut: number;
        while ((cut = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, cut);
          buf = buf.slice(cut + 2);
          const data = block.split("\n").find((l) => l.startsWith("data: "));
          if (!data) continue;
          const e = JSON.parse(data.slice(6)) as ChatEvent;
          onEvent(e);
          if (e.type === "done") return e.answer;
          if (e.type === "error") throw new ApiError(503, e.message);
        }
        if (done) throw new ApiError(502, "The answer stopped before it was complete.");
      }
    },
    reference: (text: string) => call<ReferenceResult>("/assist/reference", { text }),
    docContext: (canonicalId: string, quote: string) =>
      call<PassageContext>(`${doc(canonicalId)}/context?quote=${encodeURIComponent(quote)}`),
    digest: (days = 7) => call<Digest>(`/assist/digest?days=${days}`),
    roles: () => call<{ monitoring: boolean }>("/assist/me/roles"),
    monitor: (days = 14) => call<MonitorData>(`/assist/monitor?days=${days}`),
    reviewAlert: (alertId: string, action: "reviewed" | "escalated", reason?: "expected_activity") =>
      call<{ alert_id: string; status: string }>(
        `/assist/monitor/alerts/${encodeURIComponent(alertId)}/review`,
        reason ? { action, reason } : { action },
      ),
    feedback: (body: FeedbackIn) => call<{ request_id: string; recorded: boolean }>("/assist/feedback", body),
    // The officer's own e-Office actions on their drafts (sandbox; simulated signature, no DSC).
    saveDraft: (computerNo: string, draftId: string, text: string) =>
      call<{ draft_id: string; versions: number }>(`${draftPath(computerNo, draftId)}/save`, { text }),
    confirmDraft: (computerNo: string, draftId: string) =>
      call<{ draft_id: string; note_id: string; state: "green" }>(`${draftPath(computerNo, draftId)}/confirm`, {}),
    discardDraft: (computerNo: string, draftId: string) =>
      call<{ draft_id: string; status: "discarded" }>(`${draftPath(computerNo, draftId)}/discard`, {}),
    insertYellowNote: (computerNo: string, body: string, citations: string[], requestId: string) =>
      call<DraftReceipt>("/assist/draft", {
        computer_no: computerNo, kind: "yellow_note", body, citations, request_id: requestId,
      }),
    // A DFA's way to issue (ADR-0045): the author puts it up; another officer approves and issues.
    submitDraft: (computerNo: string, draftId: string) =>
      call<{ draft_id: string; status: string }>(`${draftPath(computerNo, draftId)}/submit`, {}),
    approveAndIssue: (computerNo: string, draftId: string) =>
      call<{ draft_id: string; status: string; issued_as: string }>(`${approvalPath(computerNo, draftId)}/issue`, {}),
    returnDraft: (computerNo: string, draftId: string, remarks?: string) =>
      call<{ draft_id: string; status: string; review_remarks?: string | null }>(
        `${approvalPath(computerNo, draftId)}/return`,
        remarks ? { remarks } : {},
      ),
    reviseDraft: (computerNo: string, draftId: string | undefined, currentText: string, reviewRemarks: string) =>
      call<{ revised_text: string; changes_summary: string; engine?: string | null; fallback?: boolean; reason?: string | null }>(
        "/assist/draft/revise",
        { computer_no: computerNo, draft_id: draftId, current_text: currentText, review_remarks: reviewRemarks },
      ),
    /** Attach a paper: the file itself is the body (no form encoding); the name rides in the query. */
    attach: async (computerNo: string, file: File): Promise<{ attachment_id: string; filename: string }> => {
      const res = await fetchFn(
        `/sandbox/files/${encodeURIComponent(computerNo)}/attachments?name=${encodeURIComponent(file.name)}`,
        { method: "POST", headers: { ...headersFor(userId), "Content-Type": "application/octet-stream" }, body: file },
      );
      if (!res.ok) {
        let detail = res.status === 413 ? "The file is too large (10 MB at most)." : res.statusText || "Request failed";
        try { detail = ((await res.json()) as { detail?: string }).detail ?? detail; } catch { /* keep */ }
        throw new ApiError(res.status, detail);
      }
      return (await res.json()) as { attachment_id: string; filename: string };
    },
    fileRecords: (computerNo: string) => call<FileRecords>(`/assist/files/${encodeURIComponent(computerNo)}/records`),
    // Draft recovery (ADR-0046): the workspace the server keeps as the officer works.
    getWorkspace: (computerNo: string | null) =>
      call<{ workspace: DraftWorkspace | null; saved_at: string | null }>(
        `/assist/draft/workspace${computerNo ? `?computer_no=${encodeURIComponent(computerNo)}` : ""}`),
    saveWorkspace: (computerNo: string | null, workspace: DraftWorkspace) =>
      call<{ saved_at: string }>("/assist/draft/workspace", { computer_no: computerNo, workspace }),
    /** The last save as the page goes away (tab closed, screen locked): `keepalive` lets the
     *  request finish after the page is gone; nothing waits for the answer. */
    saveWorkspaceOnLeave: (computerNo: string | null, workspace: DraftWorkspace) => {
      void fetchFn("/assist/draft/workspace", {
        method: "POST", keepalive: true, headers: headersFor(userId, true),
        body: JSON.stringify({ computer_no: computerNo, workspace }),
      }).catch(() => { /* the debounced save already kept all but the last moment */ });
    },
    discardWorkspace: (computerNo: string | null) =>
      call<{ discarded: boolean }>("/assist/draft/workspace/discard", { computer_no: computerNo }),
  };
}

export type Api = ReturnType<typeof createApi>;
