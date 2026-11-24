import { useState } from "react";
import type { Api } from "../api";
import { ChatPanel } from "./ChatPanel";
import { DocumentViewer } from "./Citations";

/** Ask AI: the general conversation in the assistant panel (on a file, the file fills its own Ask
 *  tab). Answers come only from records the officer may see, each line with its source, checked
 *  before it is shown; a file or order the officer may not see is "not available", exactly like
 *  one that does not exist. The conversation stays while the officer moves between screens,
 *  until sign-out. */
export function AskAi({ api, open, computerNo, fileNo }: {
  api: Api; open: boolean; onClose?: () => void; computerNo?: string; fileNo?: string;
}) {
  const [viewing, setViewing] = useState<string | null>(null);
  return (
    <>
      <div className="askai" hidden={!open}>
        <p className="muted small askai-scope">
          {fileNo ? <>About file <strong>{fileNo}</strong> and the records you may see.</> : "About the files and records you may see."}
        </p>
        {/* one conversation per place: a file's questions stay with that file */}
        <ChatPanel key={computerNo ?? "all"} titled={false} api={api} computerNo={computerNo} onOpenDoc={setViewing}
          suggestions={fileNo
            ? ["What was decided in this file?", "Which orders apply to this file, and are they still in force?", "What is attached to this file?"]
            : ["Which orders on transfers are in force now?", "Has a spouse-grounds transfer been decided before?", "What superseded G.O.Ms.No.88 of 2022?"]} />
      </div>
      {viewing && <DocumentViewer api={api} canonicalId={viewing} onClose={() => setViewing(null)} />}
    </>
  );
}
