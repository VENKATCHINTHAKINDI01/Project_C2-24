import { describe, expect, it } from "vitest";
import { ApiError, SANDBOX_USER_HEADER, createApi, headersFor } from "./api";

function fakeFetch(status: number, body: unknown, seen: { url?: string; init?: RequestInit } = {}) {
  return async (url: string, init?: RequestInit) => {
    seen.url = url; seen.init = init;
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  };
}

describe("api client", () => {
  it("sends the simulated sign-in header only when signed in", () => {
    expect(headersFor("U01")).toEqual({ [SANDBOX_USER_HEADER]: "U01" });
    expect(headersFor(null)).toEqual({});
    expect(headersFor("U01", true)["Content-Type"]).toBe("application/json");
  });

  it("posts pre-send for the open file", async () => {
    const seen: { url?: string; init?: RequestInit } = {};
    const api = createApi("U01", fakeFetch(200, { outcome: "clear" }, seen));
    await api.presend("2894562");
    expect(seen.url).toBe("/assist/presend");
    expect(seen.init?.method).toBe("POST");
    expect(JSON.parse(String(seen.init?.body))).toEqual({ computer_no: "2894562" });
  });

  it("keeps the server's neutral wording on errors", async () => {
    const api = createApi("U03", fakeFetch(404, { detail: "This file isn't available to you. If you need it for your work, please request access or approval from the competent authority through e-Office (your section / controlling officer)." }));
    await expect(api.file("2894562")).rejects.toEqual(new ApiError(404, "This file isn't available to you. If you need it for your work, please request access or approval from the competent authority through e-Office (your section / controlling officer)."));
  });

  it("reviews an alert with fixed codes only (ADR-0036)", async () => {
    const seen: { url?: string; init?: RequestInit } = {};
    const api = createApi("M01", fakeFetch(200, { alert_id: "AL-0123456789abcdef", status: "reviewed" }, seen));
    await api.reviewAlert("AL-0123456789abcdef", "reviewed", "expected_activity");
    expect(seen.url).toBe("/assist/monitor/alerts/AL-0123456789abcdef/review");
    expect(JSON.parse(String(seen.init?.body))).toEqual({ action: "reviewed", reason: "expected_activity" });
  });

  it("asks for a yellow-note draft, never anything else", async () => {
    const seen: { url?: string; init?: RequestInit } = {};
    const api = createApi("U01", fakeFetch(200, { status: "draft" }, seen));
    await api.insertYellowNote("2894562", "1. point", ["AP-FIN01-GOMS-31-2025"], "req-1");
    const body = JSON.parse(String(seen.init?.body));
    expect(seen.url).toBe("/assist/draft");
    expect(body.kind).toBe("yellow_note");
  });

  it("reads a streamed answer however the network cuts it, and returns the final answer", async () => {
    const final = { session_id: "s1", statements: [{ text: "B" }] };
    const sse = [
      { type: "stage", stage: "searching" },
      { type: "statement", statement: { text: "A {x}" } },
      { type: "done", answer: final },
    ].map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join("");
    const bytes = new TextEncoder().encode(sse);
    const body = new ReadableStream<Uint8Array>({
      start(c) { for (let i = 0; i < bytes.length; i += 5) c.enqueue(bytes.slice(i, i + 5)); c.close(); },
    });
    const seen: { url?: string; init?: RequestInit } = {};
    const api = createApi("V14", async (url, init) => {
      seen.url = url; seen.init = init;
      return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
    });
    const events: string[] = [];
    const got = await api.chatStream("q", null, undefined, (e) => events.push(e.type));
    expect(seen.url).toBe("/assist/chat/stream");
    expect(events).toEqual(["stage", "statement", "done"]);
    expect(got).toEqual(final);
  });

  it("a stream that ends with an error rejects with the server's neutral words", async () => {
    const msg = "The request could not be completed right now. Please try again later.";
    const api = createApi("V14", async () => new Response(
      `event: error\ndata: ${JSON.stringify({ type: "error", message: msg })}\n\n`, { status: 200 }));
    await expect(api.chatStream("q", null, undefined, () => {})).rejects.toThrow(msg);
  });

  it("sends feedback as IDs and a fixed code only", async () => {
    const seen: { url?: string; init?: RequestInit } = {};
    const api = createApi("U01", fakeFetch(200, { recorded: true }, seen));
    await api.feedback({ kind: "conflict_flag", request_id: "req-1", action: "dismissed", computer_no: "2894562",
      flag_type: "A", canonical_id: "AP-FIN01-GOMS-88-2022", reason: "already_handled" });
    expect(seen.url).toBe("/assist/feedback");
    expect(Object.keys(JSON.parse(String(seen.init?.body))).sort()).toEqual(
      ["action", "canonical_id", "computer_no", "flag_type", "kind", "reason", "request_id"]);
  });

  it("the officer's draft actions go to the sandbox (e-Office), never to the assistant", async () => {
    const urls: string[] = [];
    const api = createApi("U01", async (url) => { urls.push(url); return new Response("{}", { status: 200 }); });
    await api.saveDraft("2894562", "MOCK-DRAFT-00001", "text");
    await api.confirmDraft("2894562", "MOCK-DRAFT-00001");
    await api.discardDraft("2894562", "MOCK-DRAFT-00002");
    expect(urls).toEqual([
      "/sandbox/files/2894562/drafts/MOCK-DRAFT-00001/save",
      "/sandbox/files/2894562/drafts/MOCK-DRAFT-00001/confirm",
      "/sandbox/files/2894562/drafts/MOCK-DRAFT-00002/discard",
    ]);
  });

  it("fetches a stored file with the sign-in header, never through a bare URL", async () => {
    const seen: { url?: string; init?: RequestInit } = {};
    const api = createApi("U01", async (url, init) => {
      seen.url = url; seen.init = init;
      return new Response(new Uint8Array([37, 80, 68, 70]), { status: 200, headers: { "Content-Type": "application/pdf" } });
    });
    const b = await api.documentFile("AP-FIN01-GOMS-88-2022", "preview");
    expect(seen.url).toBe("/assist/documents/AP-FIN01-GOMS-88-2022/preview");
    expect((seen.init?.headers as Record<string, string>)[SANDBOX_USER_HEADER]).toBe("U01");
    expect(b.size).toBe(4);
  });

  it("a document the officer may not see fails with the neutral wording", async () => {
    const api = createApi("U03", fakeFetch(404, { detail: "This document isn't available to you. If you need it for your work, please request access or approval from the competent authority through e-Office (your section / controlling officer)." }));
    await expect(api.documentFile("AP-X", "download")).rejects.toEqual(new ApiError(404, "This document isn't available to you. If you need it for your work, please request access or approval from the competent authority through e-Office (your section / controlling officer)."));
    await expect(api.documentInfo("AP-X")).rejects.toEqual(new ApiError(404, "This document isn't available to you. If you need it for your work, please request access or approval from the competent authority through e-Office (your section / controlling officer)."));
  });

  it("sends the reviewer's correction only when the text was edited", async () => {
    const seen: { url?: string; init?: RequestInit } = {};
    const api = createApi("U03", fakeFetch(200, { status: "indexed" }, seen));
    await api.ocrConfirm("RV-000007", "checked against the scan", null);
    expect(seen.url).toBe("/assist/review/ocr/RV-000007/confirm");
    expect(JSON.parse(String(seen.init?.body))).toEqual({ reason: "checked against the scan", corrected_text: null });
    await api.ocrReject("RV-000007", "needs re-scan");
    expect(seen.url).toBe("/assist/review/ocr/RV-000007/reject");
  });
});
