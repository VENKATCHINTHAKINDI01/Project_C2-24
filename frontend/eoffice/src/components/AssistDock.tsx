import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { MessageSquare, PanelRightClose, PanelRightOpen, PenLine, ShieldCheck, type LucideIcon } from "lucide-react";

/** The assistant's one docked panel (UI redesign, 24 Nov 2026): tabs Ask · Check · Draft, on the
 *  right of every screen, collapsible to an icon strip. The page that knows the context (a file,
 *  a receipt) fills the tabs through portals, so its tools keep their state in the page that owns
 *  them; elsewhere the panel holds the general Ask conversation. */
export type DockTab = "ask" | "check" | "draft";

const TABS: Record<DockTab, { label: string; icon: LucideIcon; hint: string }> = {
  ask: { label: "Ask", icon: MessageSquare, hint: "Ask about the records you may see" },
  check: { label: "Check", icon: ShieldCheck, hint: "Understand and check before sending" },
  draft: { label: "Draft", icon: PenLine, hint: "Prepare drafts for your approval" },
};

interface DockApi {
  /** the tabs the current page fills, and what the panel is about */
  claim: (tabs: DockTab[], about: ReactNode) => void;
  release: () => void;
  slot: (tab: DockTab) => HTMLElement | null;
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

export function AssistDock({ open, setOpen, general, children }: {
  open: boolean; setOpen: (o: boolean) => void;
  /** the general Ask conversation, shown when the page fills no Ask tab of its own */
  general: ReactNode;
  children: ReactNode;
}) {
  const [claimed, setClaimed] = useState<{ tabs: DockTab[]; about: ReactNode } | null>(null);
  const [tab, setTab] = useState<DockTab>("ask");
  const [slots, setSlots] = useState<Partial<Record<DockTab, HTMLElement | null>>>({});
  const claim = useCallback((tabs: DockTab[], about: ReactNode) => {
    setClaimed({ tabs, about });
    setTab((t) => (tabs.includes(t) || t === "ask" ? t : tabs[0]));
  }, []);
  const release = useCallback(() => { setClaimed(null); setTab("ask"); }, []);
  const slot = useCallback((t: DockTab) => slots[t] ?? null, [slots]);
  const show = useCallback((t: DockTab) => { setTab(t); setOpen(true); }, [setOpen]);
  // one stable ref callback per tab: a new callback each render would detach and re-attach the slot
  const refs = useMemo(() => Object.fromEntries((["ask", "check", "draft"] as DockTab[]).map((t) =>
    [t, (el: HTMLElement | null) => setSlots((s) => (s[t] === el ? s : { ...s, [t]: el }))])) as Record<DockTab, (el: HTMLElement | null) => void>, []);

  const value = useMemo(() => ({ claim, release, slot, show }), [claim, release, slot, show]);
  const pageTabs = claimed?.tabs ?? [];
  const tabs: DockTab[] = pageTabs.includes("ask") ? pageTabs : ["ask", ...pageTabs];
  const active = tabs.includes(tab) ? tab : "ask";
  const ownAsk = pageTabs.includes("ask");

  // Ctrl/⌘+K anywhere: open the panel on Ask (ChatPanel focuses the box)
  useEffect(() => {
    const onAsk = () => { setTab("ask"); setOpen(true); };
    window.addEventListener("c2:ask", onAsk);
    return () => window.removeEventListener("c2:ask", onAsk);
  }, [setOpen]);
  useEffect(() => {
    if (!open || active !== "ask") return undefined;
    const t = window.setTimeout(() => {
      document.querySelector<HTMLElement>(".dock-pane.active .chat input")?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(t);
  }, [open, active]);

  return (
    <DockContext.Provider value={value}>
      {children}
      <aside className={`dock${open ? "" : " collapsed"}`} aria-label="Assistant">
        <div className="dock-strip" hidden={open}>
          <button className="icon-btn" onClick={() => setOpen(true)} aria-label="Open the assistant" title="Open the assistant">
            <PanelRightOpen size={18} aria-hidden="true" />
          </button>
          {tabs.map((t) => {
            const { icon: Icon, label, hint } = TABS[t];
            return (
              <button key={t} className="icon-btn" onClick={() => show(t)} aria-label={`${label}: ${hint}`} title={`${label} — ${hint}`}>
                <Icon size={18} aria-hidden="true" />
              </button>
            );
          })}
        </div>
        <div className="dock-body" hidden={!open}>
          <header className="dock-head">
            <div className="dock-title">
              <h2>Assistant</h2>
              <p>{claimed?.about ?? "About the files and records you may see"}</p>
            </div>
            <button className="icon-btn" onClick={() => setOpen(false)} aria-label="Collapse the assistant" title="Collapse the assistant">
              <PanelRightClose size={18} aria-hidden="true" />
            </button>
          </header>
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
            <div className={`dock-pane${active === "ask" && !ownAsk ? " active" : ""}`} hidden={!(active === "ask" && !ownAsk)}>{general}</div>
            {pageTabs.map((t) => (
              <div key={t} ref={refs[t]} role="tabpanel" className={`dock-pane${active === t ? " active" : ""}`} hidden={active !== t} />
            ))}
          </div>
        </div>
      </aside>
    </DockContext.Provider>
  );
}
