import { useEffect, useMemo, useState } from "react";
import { createApi } from "./api";
import { Banner } from "./components/Banner";
import { FileList } from "./components/FileList";
import { FilePageView } from "./components/FilePageView";
import { ReceiptInbox, ReceiptView } from "./components/Receipts";
import { MonitorPad } from "./components/MonitorPad";
import { OcrReview } from "./components/OcrReview";
import { SearchPage } from "./components/SearchPage";
import { SignIn } from "./components/SignIn";
import { TopBar, type View } from "./components/TopBar";
import type { Profile } from "./types";

export function App() {
  const [me, setMe] = useState<Profile | null>(null);
  const [view, setView] = useState<View>({ kind: "files" });
  const api = useMemo(() => createApi(me?.user_id ?? null), [me]);
  const [monitoring, setMonitoring] = useState(false);
  // the server says whether this officer has the monitoring pad; a monitoring officer lands on it
  useEffect(() => {
    setMonitoring(false);
    if (!me) return;
    api.roles().then((r) => { setMonitoring(r.monitoring); if (r.monitoring) setView({ kind: "monitor" }); })
      .catch(() => setMonitoring(false));
  }, [api, me]);
  return (
    <div className="app">
      <Banner />
      {!me ? (
        <SignIn api={api} onSignIn={(p) => { setMe(p); setView({ kind: "files" }); }} />
      ) : (
        <>
          <TopBar me={me} view={view} go={setView} signOut={() => setMe(null)} monitoring={monitoring} />
          {view.kind === "monitor" && monitoring && <MonitorPad api={api} />}
          {view.kind === "files" && <FileList api={api} open={(c) => setView({ kind: "file", computerNo: c })} />}
          {view.kind === "file" && <FilePageView key={view.computerNo} api={api} computerNo={view.computerNo} open={(c) => setView({ kind: "file", computerNo: c })} />}
          {view.kind === "search" && <SearchPage api={api} />}
          {view.kind === "receipts" && <ReceiptInbox api={api} open={(c) => setView({ kind: "receipt", computerNo: c })} />}
          {view.kind === "review" && <OcrReview api={api} />}
          {view.kind === "receipt" && <ReceiptView key={view.computerNo} api={api} computerNo={view.computerNo} />}
        </>
      )}
    </div>
  );
}
