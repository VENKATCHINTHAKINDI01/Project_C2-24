// Turning a pre-send report into words the officer reads and, on click, a Yellow Note DRAFT.
// Deterministic text from the flags themselves — no model output (Gemini comes with GCP).
import type { Flag, PresendReport } from "./types";

export const FLAG_NAMES: Record<Flag["type"], string> = {
  A: "Superseded reference", B: "Rule contradiction", C: "Procedure / authority",
  D: "Precedent inconsistency", E: "Missing authority", F: "Temporal mismatch",
  G: "Hierarchy conflict",
};

export function outcomeLabel(r: PresendReport): string {
  if (r.outcome === "conflicts_found") return "Pre-send check — review recommended";
  if (r.outcome === "clear") return "Pre-send check — no conflicts found in a verified rule set";
  return "Pre-send check — review needed (not enough verified rules or facts to say it is clear)";
}

/** Body for "Insert as Yellow Note": the flags as numbered points, each with its sources. */
export function yellowNoteFrom(r: PresendReport): { body: string; citations: string[] } {
  const flags = r.flags ?? [];
  const citations = [...new Set(flags.flatMap((f) => f.evidence_ids))];
  const lines = flags.map((f, i) => {
    const src = f.evidence_ids.length ? ` [${f.evidence_ids.join("; ")}]` : "";
    return `${i + 1}. ${FLAG_NAMES[f.type]}: ${f.explanation}${src}`;
  });
  const head = "Points for consideration before the file is sent (C2-24 pre-send check, draft):";
  return { body: [head, ...lines].join("\n"), citations };
}
