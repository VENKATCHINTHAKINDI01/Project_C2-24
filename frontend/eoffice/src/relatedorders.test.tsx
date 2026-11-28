import { describe, expect, it } from "vitest";
import { linkLine, orderName } from "./components/RelatedOrders";
import type { OrderLink } from "./types";

const base: OrderLink = {
  source: "AP-ESE01-GOMS-29-2021", kind: "SUPERSEDES", target: "AP-ESE01-GOMS-8-2021", this_is: "newer",
  other: { canonical_id: "AP-ESE01-GOMS-8-2021", subject: "Transfers", issue_date: null },
  state: "suggested", score: 0, officers: 0, stated_in_text: false, contested: false, evidence_requested: false,
  decided_post: null, decided_at: null, wording: null, can_flag: true, can_validate: false,
};

describe("related orders wording (ADR-0074)", () => {
  it("names G.O.s as officers write them", () => {
    expect(orderName("AP-ESE01-GOMS-8-2021")).toBe("G.O.Ms.No.8/2021");
    expect(orderName("AP-USD01-GORT-233-2024")).toBe("G.O.Rt.No.233/2024");
  });
  it("never calls an inferred link confirmed, and never says 'yet to be validated'", () => {
    for (const state of ["candidate", "suggested", "supported_by_use"] as const) {
      const t = linkLine({ ...base, state, officers: 3 });
      expect(t).toMatch(/Please review/);
      expect(t).not.toMatch(/validated|unverified|confirmed/i);
    }
    expect(linkLine({ ...base, state: "supported_by_use", officers: 3 })).toContain("appears to replace");
  });
  it("says who confirmed a link, or that the order states it", () => {
    expect(linkLine({ ...base, state: "validated", stated_in_text: true })).toBe("This order replaces G.O.Ms.No.8/2021 (stated in the order).");
    expect(linkLine({ ...base, state: "validated", decided_post: "Deputy Secretary" })).toContain("confirmed by the Deputy Secretary");
    expect(linkLine({ ...base, this_is: "older", state: "suggested" })).toBe("G.O.Ms.No.8/2021 appears to replace this order. Please review before relying on it.");
  });
});
