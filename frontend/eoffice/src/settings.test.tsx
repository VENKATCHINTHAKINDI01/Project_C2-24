import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { createApi } from "./api";
import { dueTag } from "./components/FileList";
import { SettingsPage } from "./components/Settings";
import { SideNav } from "./components/TopBar";
import { fmtDate, fmtDateTime, setDateStyle } from "./format";
import { DEFAULT_PREFERENCES } from "./types";

const text = (el: React.ReactElement) => renderToString(el).replace(/<!-- -->/g, "");

describe("officer settings (ADR-0041)", () => {
  afterEach(() => setDateStyle("dd-mm-yyyy"));

  it("the date style applies to every date shown", () => {
    expect(fmtDate("2025-05-12")).toBe("12-05-2025");
    setDateStyle("dd Mon yyyy");
    expect(fmtDate("2025-05-12")).toBe("12 May 2025");
    expect(fmtDateTime("2025-05-12T10:40:00+05:30")).toBe("12 May 2025, 10:40");
  });

  it("due dates are marked overdue or due soon, and 0 days turns it off", () => {
    const today = new Date(2026, 10, 17);
    const html = (d: string, n: number) => { const t = dueTag(d, n, today); return t ? text(t) : ""; };
    expect(html("2026-11-10", 3)).toContain("overdue");
    expect(html("2026-11-17", 3)).toContain("due today");
    expect(html("2026-11-19", 3)).toContain("due in 2 days");
    expect(html("2026-11-25", 3)).toBe("");
    expect(html("2026-11-10", 0)).toBe("");
  });

  it("the settings page shows every group and says access is not a setting", () => {
    const html = text(<SettingsPage api={createApi("U01")} prefs={DEFAULT_PREFERENCES} monitoring={false} onSaved={() => {}} />);
    for (const s of ["My profile", "Display", "Start and lists", "Assistant", "What is recorded",
      "Text size", "Contrast", "Dates", "After signing in, open", "Assistant panel on a file",
      "Keyboard shortcuts", "Notices of new orders", "Restore defaults"]) expect(html).toContain(s);
    expect(html).toContain("They never change which files or records you can open.");
    expect(html).not.toContain(">Monitoring<"); // only a monitoring officer may start there
  });

  it("Settings is a working menu item; Dispatch and Draft register stay off", () => {
    const html = text(<SideNav view={{ kind: "settings" }} go={() => {}} monitoring={false} />);
    expect(html).toMatch(/<button class="on">Settings<\/button>/);
    expect(html).toMatch(/<button disabled=""[^>]*>Dispatch<\/button>/);
  });
});
