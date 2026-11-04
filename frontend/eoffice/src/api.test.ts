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
    const api = createApi("U03", fakeFetch(404, { detail: "File not available." }));
    await expect(api.file("2894562")).rejects.toEqual(new ApiError(404, "File not available."));
  });

  it("asks for a yellow-note draft, never anything else", async () => {
    const seen: { url?: string; init?: RequestInit } = {};
    const api = createApi("U01", fakeFetch(200, { status: "draft" }, seen));
    await api.insertYellowNote("2894562", "1. point", ["AP-FIN01-GOMS-31-2025"], "req-1");
    const body = JSON.parse(String(seen.init?.body));
    expect(seen.url).toBe("/assist/draft");
    expect(body.kind).toBe("yellow_note");
  });
});
