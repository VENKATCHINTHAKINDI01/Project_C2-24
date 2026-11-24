import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { MessageSquare, PenLine, ShieldCheck, Sparkles, X, type LucideIcon } from "lucide-react";

/** The assistant (mentor review, 24 Nov 2026; ADR-0064 addendum 1). Two entry points:
 *  - on a file (or receipt), a floating AI button at the bottom right opens a small chat panel
 *    about THAT file: Ask · Check · Draft. The page fills the tabs through portals, so its tools
 *    keep their state while the panel is closed;
 *  - Ask AI in the top bar opens the general chat over every file and record the officer may see.
 *  Neither takes a column of the page; one panel is open at a time. */
export type DockTab = "ask" | "check" | "draft";
export type AiMode = "file" | "general" | null;

const TABS: Record<DockTab, { label: string; icon: LucideIcon; hint: string }> = {
  ask: { label: "Ask", icon: MessageSquare, hint: "Ask about this file: summary, notes, movements, records" },
  check: { label: "Check", icon: ShieldCheck, hint: "Understand and check before sending" },
  draft: { label: "Draft", icon: PenLine, hint: "Prepare drafts for your approval" },
};

interface DockApi {
  /** the tabs the current page fills, and what the panel is about */
  claim: (tabs: DockTab[], about: ReactNode) => void;
  release: () => void;
  slot: (tab: DockTab) => HTMLElement | null;
  /** open the file panel on a tab */
  show: (tab: DockTab) => void;
}

export const DockContext = createContext<DockApi | null>(null);

/** A page puts its own content into the panel's tabs. Content stays mounted while hidden. */
export function useDock(tabs: DockTab[], about: ReactNode) {
  const dock = useContext(DockContext);
  const key = tabs.join(",");
  useEffect(() => {
    if (!dock) return undefined;
    dock.claim(tabs, about);
    return () => dock.release();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-claim only when the tabs change
  }, [dock?.claim, dock?.release, key]);
  return dock;
}

/** Content of one tab, rendered into the panel (or nowhere if there is no panel). */
export function DockSlot({ tab, children }: { tab: DockTab; children: ReactNode }) {
  const dock = useContext(DockContext);
  const el = dock?.slot(tab) ?? null;
  return el ? createPortal(children, el) : null;
}

function PanelHead({ title, about, close }: { title: string; about: ReactNode; close: () => void }) {
  return (
    <header className="dock-head">
      <span className="ai-mark" aria-hidden="true"><Sparkles size={16} /></span>
      <div className="dock-title">
        <h2>{title}</h2>
        <p>{about}</p>
      </div>
      <button className="icon-btn" onClick={close} aria-label="Close (Esc)" title="Close (Esc)">
        <X size={18} aria-hidden="true" />
      </button>
    </header>
  );
}

export function AssistDock({ mode, setMode, autoOpen = false, general, children }: {
  mode: AiMode; setMode: (m: AiMode) => void;
  /** open the file panel as soon as a file opens (Settings › When a file opens) */
  autoOpen?: boolean;
  /** the general conversation (top bar Ask AI): every file and record the officer may see */
  general: ReactNode;
  children: ReactNode;
}) {
  const [claimed, setClaimed] = useState<{ tabs: DockTab[]; about: ReactNode } | null>(null);
  const [tab, setTab] = useState<DockTab>("ask");
  const [slots, setSlots] = useState<Partial<Record<DockTab, HTMLElement | null>>>({});
  const claim = useCallback((tabs: DockTab[], about: ReactNode) => {
    setClaimed({ tabs, about });
    setTab((t) => (tabs.includes(t) ? t : tabs[0]));
    if (autoOpen) setMode("file");
  }, [autoOpen, setMode]);
  // leaving the file closes its panel; the general chat, if open, stays open
  const release = useCallback(() => { setClaimed(null); setTab("ask"); }, []);
  const slot = useCallback((t: DockTab) => slots[t] ?? null, [slots]);
  const show = useCallback((t: DockTab) => { setTab(t); setMode("file"); }, [setMode]);
  // one stable ref callback per tab: a new callback each render would detach and re-attach the slot
  const refs = useMemo(() => Object.fromEntries((["ask", "check", "draft"] as DockTab[]).map((t) =>
    [t, (el: HTMLElement | null) => setSlots((s) => (s[t] === el ? s : { ...s, [t]: el }))])) as Record<DockTab, (el: HTMLElement | null) => void>, []);

  const value = useMemo(() => ({ claim, release, slot, show }), [claim, release, slot, show]);
  const tabs = claimed?.tabs ?? [];
  const active = tabs.includes(tab) ? tab : tabs[0];
  const fileOpen = mode === "file" && tabs.length > 0;
  // left the file: its panel closes with it (the next file starts with just the button)
  useEffect(() => { if (!claimed && mode === "file") setMode(null); }, [claimed, mode, setMode]);

  // Ctrl/⌘+K: on a file its own chat, elsewhere the general one (ChatPanel focuses the box)
  useEffect(() => {
    const onAsk = () => {
      if (claimed) show(claimed.tabs.includes("ask") ? "ask" : claimed.tabs[0]);
      else setMode("general");
    };
    window.addEventListener("c2:ask", onAsk);
    return () => window.removeEventListener("c2:ask", onAsk);
  }, [claimed, show, setMode]);
  // Esc closes the open panel (unless a document viewer or another dialog is on top)
  useEffect(() => {
    if (!mode) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || document.querySelector(".doc-viewer, [role=dialog]:not(.ai-panel)")) return;
      setMode(null);
      window.setTimeout(() => document.querySelector<HTMLElement>(".ai-fab")?.focus(), 0);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mode, setMode]);
  useEffect(() => {
    if (!mode) return undefined;
    const t = window.setTimeout(() => {
      document.querySelector<HTMLElement>(".ai-panel:not([hidden]) .dock-pane.active .chat input")?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(t);
  }, [mode, active]);

  return (
    <DockContext.Provider value={value}>
      {children}
      {tabs.length > 0 && !fileOpen && (
        <button className="ai-fab" onClick={() => show(tabs.includes("ask") ? "ask" : tabs[0])}
          aria-label="Ask AI about this file (Ctrl+K)" title="Ask AI about this file (Ctrl+K)">
          <Sparkles size={22} aria-hidden="true" />
        </button>
      )}
      {/* the file's own panel: mounted while the page claims it, so its tools keep their state */}
      {tabs.length > 0 && (
        <aside className="ai-panel" role="dialog" aria-modal="false" aria-label="AI assistant for this file" hidden={!fileOpen}>
          <PanelHead title="Ask AI" about={claimed?.about} close={() => setMode(null)} />
          {tabs.length > 1 && (
            <div className="dock-tabs" role="tablist" aria-label="Assistant tools">
              {tabs.map((t) => {
                const { icon: Icon, label, hint } = TABS[t];
                return (
                  <button key={t} role="tab" aria-selected={active === t} className={active === t ? "on" : undefined}
                    title={hint} onClick={() => setTab(t)}>
                    <Icon size={16} aria-hidden="true" />{label}
                  </button>
                );
              })}
            </div>
          )}
          <div className="dock-panes">
            {tabs.map((t) => (
              <div key={t} ref={refs[t]} role="tabpanel" className={`dock-pane${active === t ? " active" : ""}`} hidden={active !== t} />
            ))}
          </div>
        </aside>
      )}
      {/* the general chat: kept mounted, so the conversation stays until sign-out */}
      <aside className="ai-panel general" role="dialog" aria-modal="false" aria-label="Ask AI about all your files" hidden={mode !== "general"}>
        <PanelHead title="Ask AI" about="All files and records you may open" close={() => setMode(null)} />
        <div className="dock-panes"><div className="dock-pane active">{general}</div></div>
      </aside>
    </DockContext.Provider>
  );
}
