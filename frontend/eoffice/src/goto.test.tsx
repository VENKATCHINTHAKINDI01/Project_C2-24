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
    const html = text(<TopBar me={me} signOut={() => {}} files={FILES} dark={false} toggleTheme={() => {}} />);
    expect(html).toContain('aria-label="Go to file"');
    expect(html).toContain("Switch to the dark theme");
  });

  it("Recent lists files opened in this sign-in", () => {
    const html = text(<SideNav view={{ kind: "files", folder: "inbox" }} go={() => {}} monitoring={false}
      recent={[{ computerNo: "1771342", fileNo: "USD01-12/19/2026-ESTT.I" }]} />);
    expect(html).toContain("Recent");
    expect(html).toContain("USD01-12/19/2026-ESTT.I");
    expect(text(<SideNav view={{ kind: "settings" }} go={() => {}} monitoring={false} />)).not.toContain(">Recent<");
  });

  it("theme: Light, Dark and Match my computer are offered; light and dark resolve to themselves", () => {
    const html = text(<SettingsPage api={createApi("U01")} prefs={DEFAULT_PREFERENCES} monitoring={false} onSaved={() => {}} />);
    for (const s of ["Theme", "Light", "Dark", "Match my computer"]) expect(html).toContain(s);
    expect(resolveTheme("dark")).toBe("dark");
    expect(resolveTheme("light")).toBe("light");
    expect(["light", "dark"]).toContain(resolveTheme("system"));
  });
});
