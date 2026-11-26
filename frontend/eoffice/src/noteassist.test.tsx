import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MIN_POLISH_WORDS, SuggestedNotes, wordCount, wordDiff } from "./components/NoteAssist";
import type { Api } from "./api";

describe("Polish and suggested notes (ADR-0072)", () => {
  it("shows what Polish changed, word by word", () => {
    const d = wordDiff("pls approve the draft", "Please approve the draft.");
    expect(d.filter((p) => p.kind === "del").map((p) => p.text.trim())).toEqual(["pls", "draft"]);
    expect(d.filter((p) => p.kind === "ins").map((p) => p.text)).toEqual(["Please", "draft."]);
    expect(d.filter((p) => p.kind !== "del").map((p) => p.text).join("")).toBe("Please approve the draft.");
  });

  it("offers Polish only from twelve words, as Gmail does", () => {
    expect(MIN_POLISH_WORDS).toBe(12);
    expect(wordCount("  as per DS orders  draft go rt\nprepared ")).toBe(8);
  });

  it("asks for suggestions only once the officer starts writing", () => {
    let asked = 0;
    const api = { noteSuggestions: () => { asked++; return new Promise(() => {}); } } as unknown as Api;
    expect(renderToStaticMarkup(<SuggestedNotes api={api} computerNo="1001" active={false} onPick={() => {}} />)).toBe("");
    expect(asked).toBe(0);
  });
});

describe("Polish streams sentence by sentence (ADR-0072)", () => {
  it("shows each checked sentence as it arrives and returns the final result", async () => {
    const { createApi } = await import("./api");
    const final = { text: "One. Two.", mode: "polish", added: [], kept: [], reason: null, withheld: [] };
    const sse = [
      { type: "sentence", text: "One.", note_no: null, new_paragraph: false },
      { type: "sentence", text: "Two.", note_no: null, new_paragraph: false },
      { type: "done", result: final },
    ].map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join("");
    const bytes = new TextEncoder().encode(sse);
    const body = new ReadableStream<Uint8Array>({
      start(c) { for (let i = 0; i < bytes.length; i += 7) c.enqueue(bytes.slice(i, i + 7)); c.close(); },
    });
    let url = "";
    const api = createApi("U01", async (u) => { url = String(u); return new Response(body, { status: 200 }); });
    const seen: string[] = [];
    const got = await api.polishNoteStream("1001", "typed note", "polish", "", (e) => { if (e.type === "sentence") seen.push(e.text); });
    expect(url).toBe("/assist/note/polish/stream");
    expect(seen).toEqual(["One.", "Two."]);
    expect(got).toEqual(final);
  });
});
