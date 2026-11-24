import { useEffect, useMemo, useState } from "react";
import type { Api } from "../api";
import { ChatPanel, type FileTool } from "./ChatPanel";
import { fileAsk, fileTools, type FileAsk } from "./FileChatTools";
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
  // "summarise File No. X", "where is file X pending?": a file the officer can open, named by its
  // number, is answered by that file's own tools, exactly as in the file's chat (ADR-0064 add. 1)
  const [files, setFiles] = useState<Map<string, string>>(new Map());
  useEffect(() => {
    if (computerNo) return;
    api.files().then((r) => setFiles(new Map(r.files.map((f) => [f.file_no.toUpperCase(), f.computer_no])))).catch(() => undefined);
  }, [api, computerNo]);
  const tools = useMemo<FileTool[]>(() => {
    if (computerNo || files.size === 0) return [];
    const named = (q: string) => [...files.keys()].find((no) => q.toUpperCase().includes(no));
    const BY_NUMBER: FileAsk[] = ["summary", "ask_file", "movements", "brief", "since", "presend", "related", "first_cut", "dfa", "closing"];
    return BY_NUMBER.map((id) => ({
      id: `${id}@file`,
      match: (q: string) => fileAsk(q) === id && named(q) !== undefined,
      ready: (q: string) => named(q) !== undefined, // a tool here needs a file the officer named
      run: (q: string) => {
        const cno = files.get(named(q) as string) as string;
        const tool = fileTools({ api, computerNo: cno, onInserted: () => undefined, onOpenDoc: setViewing, records: () => null })
          .find((x) => x.id === id) as FileTool;
        return tool.run(q);
      },
    }));
  }, [api, computerNo, files]);
  return (
    <>
      <div className="askai" hidden={!open}>
        <p className="muted small askai-scope">
          {fileNo ? <>About file <strong>{fileNo}</strong> and the records you may see.</> : "About the files and records you may see."}
        </p>
        {/* one conversation per place: a file's questions stay with that file */}
        <ChatPanel key={computerNo ?? "all"} titled={false} api={api} computerNo={computerNo} onOpenDoc={setViewing} tools={tools}
          suggestions={fileNo
            ? ["What was decided in this file?", "Which orders apply to this file, and are they still in force?", "What is attached to this file?"]
            : ["Which orders on transfers are in force now?", "Has a spouse-grounds transfer been decided before?", "What superseded G.O.Ms.No.88 of 2022?"]} />
      </div>
      {viewing && <DocumentViewer api={api} canonicalId={viewing} onClose={() => setViewing(null)} />}
    </>
  );
}
