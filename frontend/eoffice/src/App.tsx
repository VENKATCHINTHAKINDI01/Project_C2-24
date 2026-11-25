import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createApi } from "./api";
import { Banner } from "./components/Banner";
import { FileList } from "./components/FileList";
import { FilePageView } from "./components/FilePageView";
import { HandoverPanel } from "./components/Handover";
import { MonitorPad } from "./components/MonitorPad";
import { NewFilePanel } from "./components/NewFile";
import { OcrReview } from "./components/OcrReview";
import { ReceiptInbox, ReceiptView } from "./components/Receipts";
import { SearchPage } from "./components/SearchPage";
import { SettingsPage } from "./components/Settings";
import { AskAi } from "./components/AskAi";
import { AssistDock, type AiMode } from "./components/AssistDock";
import { DraftStudio } from "./components/DraftStudio";
import { SignIn } from "./components/SignIn";
import { SideNav, TopBar, type View } from "./components/TopBar";
import { setDateStyle } from "./format";
import { currentHash, fromHash, HOME, toHash } from "./nav";
import { applyDisplay, PrefsContext, resolveTheme } from "./prefs";
import { DEFAULT_PREFERENCES, type FileRow, type Preferences, type Profile } from "./types";

const LANDING: Record<Preferences["landing"], View> = {
  inbox: HOME, receipts: { kind: "receipts" }, search: { kind: "search" }, monitor: { kind: "monitor" },
};

export function App() {
  const [me, setMe] = useState<Profile | null>(null);
  const [view, setView] = useState<View>(() => fromHash(currentHash()) ?? HOME);
  const api = useMemo(() => createApi(me?.user_id ?? null), [me]);
  const [monitoring, setMonitoring] = useState(false);
  // Every screen has its own address (nav.ts): moving to a screen adds a browser history entry,
  // so Back and Forward step through the screens the officer visited; reload keeps the screen.
  const go = useCallback((v: View, replace = false) => {
    const hash = toHash(v);
    if (window.location.hash !== hash) {
      if (replace) window.history.replaceState(null, "", hash);
      else window.history.pushState(null, "", hash);
    }
    setView(v);
    if (!replace) window.scrollTo(0, 0);
  }, []);
  useEffect(() => {
    const onPop = () => setView(fromHash(currentHash()) ?? HOME);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  // The officer's settings (ADR-0041) and whether they have the monitoring pad, both from the
  // server. After sign-in they land on the screen the address named (a bookmark, a reload), else
  // on their chosen start screen; a monitoring officer with the default lands on the pad.
  const [prefs, setPrefs] = useState<Preferences>(DEFAULT_PREFERENCES);
  const asked = useRef<View | null>(null);
  const applyPreferences = useCallback((p: Preferences) => {
    setDateStyle(p.date_style); applyDisplay(p); setPrefs(p);
  }, []);
  useEffect(() => {
    setMonitoring(false);
    if (!me) { applyPreferences(DEFAULT_PREFERENCES); return; }
    Promise.all([
      api.roles().catch(() => ({ monitoring: false })),
      api.preferences().catch(() => DEFAULT_PREFERENCES),
    ]).then(([r, p]) => {
      setMonitoring(r.monitoring);
      applyPreferences(p);
      const named = asked.current;
      let target = named ?? (r.monitoring ? LANDING.monitor : LANDING[p.landing]);
      if (target.kind === "monitor" && !r.monitoring) target = HOME;
      if (r.monitoring) target = LANDING.monitor; // the monitoring officer sees the pad only
      go(target, true);
    });
  }, [api, me, go, applyPreferences]);
  // "Match my computer": follow the system's light / dark switch while the app is open
  useEffect(() => {
    if (prefs.theme !== "system" || typeof window === "undefined" || !window.matchMedia) return undefined;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => applyDisplay(prefs);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [prefs]);
  const dark = resolveTheme(prefs.theme) === "dark";
  // one click in the top bar: switch theme and keep it (saved like any other setting)
  const toggleTheme = () => {
    const next: Preferences = { ...prefs, theme: dark ? "light" : "dark" };
    applyPreferences(next);
    api.savePreferences(next).catch(() => { /* kept for this sign-in; Settings shows the saved value */ });
  };
  // The assistant (ADR-0064 addendum 1): on a file or receipt, a floating AI button opens a chat
  // about that file; Ask AI in the top bar opens the general chat over every file the officer may
  // open. One panel at a time; neither takes a column of the page.
  const [aiMode, setAiMode] = useState<AiMode>(null);
  // the menu: full, or icons only (kept for this sign-in)
  const [navMini, setNavMini] = useState(false);
  const openFile = (c: string) => go({ kind: "file", computerNo: c });
  // The files this officer can open (from the server): folder counts, Go to file, Recent.
  const [files, setFiles] = useState<FileRow[]>([]);
  useEffect(() => {
    setFiles([]);
    if (!me) return;
    api.files().then((r) => setFiles(r.files)).catch(() => setFiles([]));
  }, [api, me, view.kind === "file"]);
  const counts = useMemo((): Record<string, number> => files.length ? {
    inbox: files.filter((f) => f.with_me).length,
    sent: files.filter((f) => f.sent_by_me).length,
    created: files.filter((f) => f.created_by_me).length,
    closed: files.filter((f) => f.state === "closed").length,
    all: files.length,
  } : {}, [files]);
  // files opened in this sign-in, newest first; forgotten at sign-out (never stored)
  const [recentNos, setRecentNos] = useState<string[]>([]);
  useEffect(() => {
    if (view.kind !== "file") return;
    const c = view.computerNo;
    setRecentNos((r) => [c, ...r.filter((x) => x !== c)].slice(0, 6));
  }, [view]);
  const recent = useMemo(() => {
    const byNo = new Map(files.map((f) => [f.computer_no, f.file_no]));
    return recentNos.filter((c) => byNo.has(c)).map((c) => ({ computerNo: c, fileNo: byNo.get(c) as string }));
  }, [recentNos, files]);
  return (
    <PrefsContext.Provider value={prefs}>
    <div className="app">
      <Banner />
      {!me ? (
        <SignIn api={api} onSignIn={(p) => {
          const named = fromHash(currentHash());
          // the default inbox address is where everyone starts, not a screen the officer asked for
          asked.current = named && toHash(named) !== toHash(HOME) ? named : null;
          setMe(p);
        }} />
      ) : (
        <>
          <TopBar me={me} signOut={() => { setMe(null); setRecentNos([]); setAiMode(null); go(HOME, true); }}
            files={files} open={monitoring ? undefined : openFile} dark={dark} toggleTheme={toggleTheme}
            ask={monitoring ? undefined : () => setAiMode(aiMode === "general" ? null : "general")} asking={aiMode === "general"} toggleNav={() => setNavMini((m) => !m)} />
          <div className={`shell${navMini ? " nav-mini" : ""}`}>
            <SideNav view={view} go={go} monitoring={monitoring} counts={counts} recent={recent} />
            <AssistDock key={me.user_id} mode={aiMode} setMode={setAiMode} autoOpen={prefs.assistant_panel === "open"}
              general={<AskAi api={api} open />}>
            <div className="main">
              {view.kind === "monitor" && monitoring && <MonitorPad api={api} />}
              {view.kind === "files" && <FileList key={view.folder} api={api} folder={view.folder} open={openFile} />}
              {view.kind === "file" && <FilePageView key={view.computerNo} api={api} computerNo={view.computerNo} open={openFile}
                draft={() => go({ kind: "draft", computerNo: view.computerNo })} />}
              {view.kind === "draft" && <DraftStudio key={`${view.computerNo}/${view.format ?? ""}`} api={api} computerNo={view.computerNo}
                initialFormat={view.format} back={() => go({ kind: "file", computerNo: view.computerNo })} onSaved={() => { /* drafts show on the file */ }} />}
              {/* New draft and the draft formats are one page: choose a format, see its layout, prepare the draft.
                  The old #/formats address opens the same page. */}
              {(view.kind === "newdraft" || view.kind === "formats") && <DraftStudio key={`new/${view.kind === "newdraft" ? view.format ?? "" : ""}`} api={api}
                initialFormat={view.kind === "newdraft" ? view.format : undefined}
                back={() => go(HOME)} onSaved={() => { /* the file list reloads when the file opens */ }} openFile={openFile} />}
              {view.kind === "newfile" && <main className="page"><NewFilePanel api={api} open={openFile} /></main>}
              {view.kind === "handover" && <main className="page"><HandoverPanel api={api} open={openFile} /></main>}
              {view.kind === "search" && <SearchPage api={api} />}
              {view.kind === "receipts" && <ReceiptInbox api={api} open={(c) => go({ kind: "receipt", computerNo: c })} />}
              {view.kind === "review" && <OcrReview api={api} />}
              {view.kind === "settings" && <SettingsPage api={api} prefs={prefs} monitoring={monitoring} onSaved={applyPreferences} />}
              {view.kind === "receipt" && <ReceiptView key={view.computerNo} api={api} computerNo={view.computerNo} />}
            </div>
            </AssistDock>
          </div>
        </>
      )}
    </div>
    </PrefsContext.Provider>
  );
}
