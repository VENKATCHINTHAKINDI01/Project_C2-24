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
