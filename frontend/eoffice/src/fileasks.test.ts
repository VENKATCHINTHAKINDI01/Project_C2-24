import { describe, expect, it } from "vitest";
import { draftFormat, fileAsk } from "./components/FileChatTools";

const which = (q: string) => fileAsk(q) ?? "search";

describe("questions in a file's chat (ADR-0064 addendum 1)", () => {
  it("the file's own records answer summary, movements, records, brief and changes", () => {
    expect(which("Summarise this file")).toBe("summary");
    expect(which("can you summarize the file")).toBe("summary");
    expect(which("What is this file about?")).toBe("summary");
    expect(which("Where is this file pending?")).toBe("movements");
    expect(which("show the movements")).toBe("movements");
    expect(which("Records on this file")).toBe("records");
    expect(which("what papers are attached to this file")).toBe("records");
    expect(which("Approval brief")).toBe("brief");
    expect(which("What changed since the decision?")).toBe("since");
  });
  it("the Check and Draft tools answer in the officer's words too", () => {
    expect(which("prepare a draft note for approval")).toBe("dfa");
    expect(which("Draft for approval")).toBe("dfa");
    expect(which("write a first-cut note")).toBe("first_cut");
    expect(which("run the pre-send check")).toBe("presend");
    expect(which("check this note before sending")).toBe("presend");
    expect(which("show related files")).toBe("related");
    expect(which("Is G.O.Ms.No.14 of 2017 still in force?")).toBe("reference");
    expect(which("refer to the earlier proposal for an enquiry")).toBe("note_ref");
    expect(which("Closing remarks")).toBe("closing");
    expect(which("what is my next action on this file")).toBe("ask_file");
    expect(which("explain what i need to do next action")).toBe("ask_file");
    expect(which("what is pending on this file")).toBe("ask_file");
    expect(which("who is the file pending with")).toBe("movements");
  });
  it("questions about orders and precedents still go to the scoped search", () => {
    for (const q of ["Has a adhoc Rules been decided before?", "What are the current rules on adhoc Rules?",
      "Draft the noting using that precedent.", "Which orders apply to this file, and are they still in force?",
      "Has this been decided before in the records?"]) {
      expect(which(q)).toBe("search");
    }
  });
});

describe("a draft for approval asked in the chat", () => {
  it("is written in the format the officer names", () => {
    expect(draftFormat("prepare a draft note for approval")).toBe("note_dfa");
    expect(draftFormat("Draft for approval")).toBe("auto"); // the file's stage decides
    expect(draftFormat("prepare a draft for this file")).toBe("auto");
    expect(draftFormat("draft the order for approval")).toBe("go_rt");
    expect(which("prepare a draft for this file")).toBe("dfa");
    expect(which("can you make a draft about this file")).toBe("dfa");
    expect(draftFormat("draft a G.O.Ms. on transfer guidelines")).toBe("go_ms");
    expect(draftFormat("draft a letter for approval to the Collector")).toBe("letter");
    expect(draftFormat("draft a circular memo for approval")).toBe("circular_memo");
  });
});
