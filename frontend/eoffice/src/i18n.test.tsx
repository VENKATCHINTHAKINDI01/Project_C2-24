import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ROWS } from "./i18n-dict";
import { translate } from "./i18n";
import { DisplayControls } from "./components/DisplayControls";

describe("screen language (ADR-0073)", () => {
  it("every row has Telugu and Hindi, and no English text is listed twice", () => {
    const seen = new Set<string>();
    for (const [en, te, hi] of ROWS) {
      expect(te.trim(), en).not.toBe("");
      expect(hi.trim(), en).not.toBe("");
      expect(seen.has(en), `duplicate: ${en}`).toBe(false);
      seen.add(en);
    }
  });
  it("translates whole labels, keeps spaces round them, and leaves everything else alone", () => {
    expect(translate("Sign out", "hi")).toBe("साइन आउट");
    expect(translate(" Sent ", "te")).toBe(" పంపినవి ");
    expect(translate("Sign out", "en")).toBeNull();
    expect(translate("Ch. Ramesh Kumar", "te")).toBeNull();
    expect(translate("F-12/2026", "hi")).toBeNull();
  });
  it("handles the sign-in patterns and comma lists", () => {
    expect(translate("Section A", "hi")).toBe("अनुभाग A");
    expect(translate("Secret clearance", "te")).toBe("రహస్యం క్లియరెన్స్");
    expect(translate("21 officers", "hi")).toBe("21 अधिकारी");
    expect(translate("Sign in as Ch. Ramesh", "te")).toBe("Ch. Ramesh గా సైన్ ఇన్ చేయండి");
    expect(translate("Section Officer, Finance", "hi")).toBe("अनुभाग अधिकारी, वित्त");
    expect(translate("Section Officer, Unknown Dept", "hi")).toBeNull();
  });
  it("shows text size and language choices", () => {
    const html = renderToStaticMarkup(<DisplayControls size="large" onSize={() => {}} />);
    expect(html).toContain("తెలుగు");
    expect(html).toContain("हिन्दी");
    expect(html).toContain('aria-label="Text size"');
    expect(html).toMatch(/title="Larger text"[^>]*|aria-pressed="true"[^>]*title="Larger text"/);
  });
});
