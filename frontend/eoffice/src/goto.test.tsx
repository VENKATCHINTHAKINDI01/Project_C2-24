import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { matchFiles } from "./components/GoTo";
import { SettingsPage } from "./components/Settings";
import { SideNav, TopBar } from "./components/TopBar";
import { createApi } from "./api";
import { resolveTheme } from "./prefs";
import { DEFAULT_PREFERENCES, type FileRow } from "./types";

const f = (computer_no: string, file_no: string, subject: string): FileRow => ({
  computer_no, file_no, subject, department: "USD01", dealing_section: "ESTT.I", category: "Establishment",
  classification: "UNCLASSIFIED", state: "open",
});
const FILES = [
  f("1771342", "USD01-12/19/2026-ESTT.I", "Request for transfer on spouse grounds"),
  f("1311050", "USD01-12/1/2020-ESTT.I", "Processing of requests for transfer of staff"),
  f("2894562", "USD01-14/6/2026-ESTT.I", "Continuation of outsourced Data Entry Operators"),
];
const text = (el: React.ReactElement) => renderToString(el).replace(/<!-- -->/g, "");

describe("faster work (ADR-0042)", () => {
  it("Go to file: exact numbers first, then starts, then subject words; nothing for no match", () => {
    expect(matchFiles(FILES, "1311050").map((x) => x.computer_no)).toEqual(["1311050"]);
    expect(matchFiles(FILES, "usd01-12/1")[0].computer_no).toBe("1311050");
    expect(matchFiles(FILES, "transfer staff").map((x) => x.computer_no)).toEqual(["1311050"]);
    expect(matchFiles(FILES, "transfer").length).toBe(2);
    expect(matchFiles(FILES, "secret vigilance")).toEqual([]);
    expect(matchFiles(FILES, "   ")).toEqual([]);
  });

  it("only files the officer can open are offered (the list the server gave)", () => {
    expect(matchFiles([], "1771342")).toEqual([]);
  });

  it("the top bar has Go to file and a one-click theme switch", () => {
    const me = { user_id: "U01", name: "Officer A", post: "Section Officer (Estt.I)", login: true } as never;
    const html = text(<TopBar me={me} signOut={() => {}} files={FILES} open={() => {}} dark={false} toggleTheme={() => {}} />);
    expect(html).toContain('aria-label="Go to file"');
    expect(html).toContain("Switch to the dark theme");
  });

  it("the menu is e-Office's own (owner, 25 Nov): Inbox, Sent, Created, Closed — no Recent or All I can open", () => {
    const html = text(<SideNav view={{ kind: "files", folder: "inbox" }} go={() => {}} monitoring={false}
      recent={[{ computerNo: "1771342", fileNo: "USD01-12/19/2026-ESTT.I" }]} />);
    for (const s of [">Receipt inbox<", ">File inbox<", ">Sent<", ">Created<", ">Closed<", ">Create new<"]) expect(html).toContain(s);
    for (const s of [">Recent<", "All I can open", "Not in this sandbox", "Parked"]) expect(html).not.toContain(s);
    expect(html.indexOf(">Search records<")).toBeGreaterThan(html.indexOf(">Create new<")); // assistant pages below
  });

  it("theme: Light, Dark and Match my computer are offered; light and dark resolve to themselves", () => {
    const html = text(<SettingsPage api={createApi("U01")} prefs={DEFAULT_PREFERENCES} monitoring={false} onSaved={() => {}} />);
    for (const s of ["Theme", "Light", "Dark", "Match my computer"]) expect(html).toContain(s);
    expect(resolveTheme("dark")).toBe("dark");
    expect(resolveTheme("light")).toBe("light");
    expect(["light", "dark"]).toContain(resolveTheme("system"));
  });
});

describe("monitoring officer (owner, 25 Nov)", () => {
  it("sees the Monitoring item only", () => {
    const html = text(<SideNav view={{ kind: "monitor" }} go={() => {}} monitoring />);
    expect(html).toContain(">Monitoring<");
    for (const s of ["inbox", ">Sent<", "Create new", "Search records", "OCR review", "Settings"]) expect(html).not.toContain(s);
  });
});
