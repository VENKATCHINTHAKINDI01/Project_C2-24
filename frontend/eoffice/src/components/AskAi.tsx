import { useEffect, useRef, useState } from "react";
import type { Api } from "../api";
import { ChatPanel } from "./ChatPanel";
import { DocumentViewer } from "./Citations";

/** Ask AI, from every screen (top bar). The same assistant as the file's panel: answers come only
 *  from records the officer may see, each line with its source, checked before it is shown; a
 *  file or order the officer may not see is "not available", exactly like one that does not
 *  exist. On a file, questions are about that file; elsewhere, about everything they may see.
 *  The conversation stays while the officer moves between screens, until sign-out. */
export function AskAi({ api, open, onClose, computerNo, fileNo }: {
  api: Api; open: boolean; onClose: () => void; computerNo?: string; fileNo?: string;
}) {
  const [viewing, setViewing] = useState<string | null>(null);
  const panel = useRef<HTMLElement>(null);
  const [top, setTop] = useState(48); // below the banner and the top bar, whatever their height

  useEffect(() => {
    if (!open) return undefined;
    const bar = document.querySelector(".topbar");
    if (bar) setTop(Math.max(0, bar.getBoundingClientRect().bottom));
    const t = window.setTimeout(() => panel.current?.querySelector<HTMLElement>("textarea, input")?.focus(), 0);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !viewing) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => { window.clearTimeout(t); window.removeEventListener("keydown", onKey); };
  }, [open, onClose, viewing]);

  return (
    <>
      <aside ref={panel} className="askai" style={{ top }} role="dialog" aria-label="Ask AI" aria-modal="false" hidden={!open}>
        <header className="askai-head">
          <div>
            <h2>Ask AI</h2>
            <p className="muted small">
              {fileNo ? <>About file <strong>{fileNo}</strong> and the records you may see.</> : "About the files and records you may see."}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close Ask AI">Close</button>
        </header>
        {/* one conversation per place: a file's questions stay with that file */}
        <ChatPanel key={computerNo ?? "all"} titled={false} api={api} computerNo={computerNo} onOpenDoc={setViewing}
          suggestions={fileNo
            ? ["What was decided in this file?", "Which orders apply to this file, and are they still in force?", "What is attached to this file?"]
            : ["Which orders on transfers are in force now?", "Has a spouse-grounds transfer been decided before?", "What superseded G.O.Ms.No.88 of 2022?"]} />
      </aside>
      {viewing && <DocumentViewer api={api} canonicalId={viewing} onClose={() => setViewing(null)} />}
    </>
  );
}
