/** The two assistants' marks (owner, 25 Nov 2026). Drawn here, not taken from an icon set, so
 *  they read as AI and cannot be mistaken for a document or chat option elsewhere in e-Office.
 *  - Office AI (all records): a speech bubble holding a gold four-point spark, with a small
 *    companion spark — a conversation about everything the officer may open.
 *  - File AI (the open file): a page with a large gold spark breaking out of its corner — the
 *    assistant working on this document. The spark is cut out of the page by `--ai-cut`
 *    (the colour behind the mark), so it stays crisp at small sizes. */

const GOLD = "#F5B700";

/** A four-point spark centred at (cx, cy) with radius r (curved, like a twinkle). */
function spark(cx: number, cy: number, r: number): string {
  const k = r * 0.34;
  return `M${cx} ${cy - r} C${cx + k} ${cy - k} ${cx + k} ${cy - k} ${cx + r} ${cy} `
    + `C${cx + k} ${cy + k} ${cx + k} ${cy + k} ${cx} ${cy + r} `
    + `C${cx - k} ${cy + k} ${cx - k} ${cy + k} ${cx - r} ${cy} `
    + `C${cx - k} ${cy - k} ${cx - k} ${cy - k} ${cx} ${cy - r}Z`;
}

export function GeneralAiIcon({ size = 18 }: { size?: number }) {
  return (
    <svg className="ai-icon general" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" fill="none">
      <path d="M5.5 3.5h13a2.5 2.5 0 0 1 2.5 2.5v8.5a2.5 2.5 0 0 1-2.5 2.5H11l-4.6 3.6a.5.5 0 0 1-.8-.4V17h-.1A2.5 2.5 0 0 1 3 14.5V6a2.5 2.5 0 0 1 2.5-2.5Z"
        stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d={spark(11.4, 10.2, 5.2)} fill={GOLD} />
      <path d={spark(17.2, 6.6, 2)} fill={GOLD} />
    </svg>
  );
}

export function FileAiIcon({ size = 18 }: { size?: number }) {
  return (
    <svg className="ai-icon file" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" fill="none">
      <path d="M6 2.5h7.6L18 6.9V12" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
      <path d="M13.4 2.6V7h4.4" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M11.5 21.5H6A1.5 1.5 0 0 1 4.5 20V4A1.5 1.5 0 0 1 6 2.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M7.8 9.8h5.6M7.8 13h3.4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d={spark(17, 17, 6.6)} fill={GOLD} stroke="var(--ai-cut, transparent)" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}
