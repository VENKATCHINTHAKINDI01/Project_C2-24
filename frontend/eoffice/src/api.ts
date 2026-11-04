// Thin client for the sandbox + assist API. Sign-in is SIMULATED with a header (sandbox only,
// ADR-0012). Errors keep the server's neutral wording; nothing is retried with less scope.
import type {
  Brief, DraftReceipt, FilePage, FileSoFar, LinkSuggestions, Notices, ReceiptReview, ReceiptRow, FileRow, Me, PresendReport, Profile, ReferenceResult, SearchResult,
} from "./types";

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
  return {
    profiles: () => call<{ banner: string; profiles: Profile[] }>("/sandbox/profiles"),
    me: () => call<Me>("/sandbox/me"),
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
    receipts: () => call<{ banner: string; receipts: ReceiptRow[] }>("/sandbox/receipts"),
    receipt: (computerNo: string) =>
      call<{ banner: string; receipt: ReceiptRow }>(`/sandbox/receipts/${encodeURIComponent(computerNo)}`),
    receiptAssist: (computerNo: string, asOf?: string) =>
      call<ReceiptReview>("/assist/receipt", asOf ? { computer_no: computerNo, as_of: asOf } : { computer_no: computerNo }),
    notices: () => call<Notices>("/assist/notices"),
    letterArrives: (computerNo: string) =>
      call<{ event_id: string; kind: string }>(`/sandbox/receipts/${encodeURIComponent(computerNo)}/arrive`, {}),
    brief: (computerNo: string) => call<Brief>("/assist/brief", { computer_no: computerNo }),
    search: (query: string) => call<SearchResult>("/assist/search", { query }),
    reference: (text: string) => call<ReferenceResult>("/assist/reference", { text }),
    insertYellowNote: (computerNo: string, body: string, citations: string[], requestId: string) =>
      call<DraftReceipt>("/assist/draft", {
        computer_no: computerNo, kind: "yellow_note", body, citations, request_id: requestId,
      }),
  };
}

export type Api = ReturnType<typeof createApi>;
