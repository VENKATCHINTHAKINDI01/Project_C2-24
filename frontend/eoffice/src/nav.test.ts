import { describe, expect, it } from "vitest";
import type { View } from "./components/TopBar";
import { fromHash, HOME, toHash } from "./nav";

describe("screen addresses (Back / Forward / reload)", () => {
  const views: View[] = [
    HOME,
    { kind: "files", folder: "closed" },
    { kind: "file", computerNo: "1771342" },
    { kind: "receipt", computerNo: "R-2026-014" },
    { kind: "newfile" }, { kind: "handover" }, { kind: "search" },
    { kind: "receipts" }, { kind: "review" }, { kind: "monitor" }, { kind: "settings" },
    { kind: "formats" }, { kind: "newdraft" }, { kind: "newdraft", format: "go_ms" }, { kind: "draft", computerNo: "1771342" }, { kind: "draft", computerNo: "1771342", format: "go_ms" },
  ];

  it("every screen has an address that leads back to the same screen", () => {
    for (const v of views) expect(fromHash(toHash(v))).toEqual(v);
    expect(new Set(views.map(toHash)).size).toBe(views.length);
  });

  it("an address names a screen, never anything more", () => {
    for (const bad of [
      "", "#", "#/", "#/nowhere", "#/files", "#/files/secret", "#/file", "#/file/a/b",
      "#/file/" + encodeURIComponent("<script>"), "#/file/%E0%A4%A", "#/search/extra",
      "#/file/" + "9".repeat(65), "#/file/..%2F..%2Fadmin",
      "#/draft/1771342/GO-MS", "#/newdraft/GO-MS", "#/newdraft/go_ms/x", "#/newdraft/1771342%2F", "#/draft/1771342/go_ms/x", "#/file/1771342/go_ms",
    ]) expect(fromHash(bad), bad).toBeNull();
  });
});
