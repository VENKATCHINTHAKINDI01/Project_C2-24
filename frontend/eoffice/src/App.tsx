import { useMemo, useState } from "react";
import { createApi } from "./api";
import { Banner } from "./components/Banner";
import { FileList } from "./components/FileList";
import { FilePageView } from "./components/FilePageView";
import { SearchPage } from "./components/SearchPage";
import { SignIn } from "./components/SignIn";
import { TopBar, type View } from "./components/TopBar";
import type { Profile } from "./types";

export function App() {
  const [me, setMe] = useState<Profile | null>(null);
  const [view, setView] = useState<View>({ kind: "files" });
  const api = useMemo(() => createApi(me?.user_id ?? null), [me]);
  return (
    <div className="app">
      <Banner />
      {!me ? (
        <SignIn api={api} onSignIn={(p) => { setMe(p); setView({ kind: "files" }); }} />
      ) : (
        <>
          <TopBar me={me} view={view} go={setView} signOut={() => setMe(null)} />
          {view.kind === "files" && <FileList api={api} open={(c) => setView({ kind: "file", computerNo: c })} />}
          {view.kind === "file" && <FilePageView key={view.computerNo} api={api} computerNo={view.computerNo} />}
          {view.kind === "search" && <SearchPage api={api} />}
        </>
      )}
    </div>
  );
}
