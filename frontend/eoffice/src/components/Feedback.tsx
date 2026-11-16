import { useState } from "react";
import type { Api } from "../api";
import type { FeedbackAction, FeedbackIn, FeedbackReason } from "../types";

/** Feedback on an output (plan §9.2; ADR-0031). Sends IDs and a fixed reason code only; it is
 *  evaluation data and changes nothing the assistant does. */
const REASONS: Record<FeedbackReason, string> = {
  wrong_source: "wrong source",
  not_relevant: "not relevant",
  outdated: "outdated",
  incomplete: "incomplete",
  not_applicable: "does not apply",
  already_handled: "already handled",
  other: "other",
};

export function Feedback({ api, target, choices }: {
  api: Api;
  target: Omit<FeedbackIn, "action" | "reason">;
  choices: [FeedbackAction, string][]; // e.g. [["thumbs_up", "👍"], ["thumbs_down", "👎"]]
}) {
  const [sent, setSent] = useState<FeedbackAction | null>(null);
  const [reason, setReason] = useState<FeedbackReason | "">("");
  const [error, setError] = useState<string | null>(null);
  const negative = (a: FeedbackAction) => a === "thumbs_down" || a === "dismissed";

  function send(action: FeedbackAction) {
    setError(null);
    api.feedback({ ...target, action, ...(negative(action) && reason ? { reason } : {}) })
      .then(() => setSent(action))
      .catch((e: Error) => setError(e.message));
  }

  if (sent) return <span className="feedback meta">Noted — thank you.</span>;
  return (
    <span className="feedback">
      {choices.map(([a, label]) => (
        <button key={a} type="button" className="fb" onClick={() => send(a)} title={a.replace("_", " ")}>{label}</button>
      ))}
      <select aria-label="Reason" value={reason} onChange={(e) => setReason(e.target.value as FeedbackReason | "")}>
        <option value="">reason (optional)</option>
        {Object.entries(REASONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      {error && <span className="error"> {error}</span>}
    </span>
  );
}
