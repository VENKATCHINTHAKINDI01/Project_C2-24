import type { Profile } from "../types";

export type View =
  | { kind: "files" } | { kind: "file"; computerNo: string } | { kind: "search" }
  | { kind: "receipts" } | { kind: "receipt"; computerNo: string } | { kind: "review" }
  | { kind: "monitor" };

export function TopBar({ me, view, go, signOut, monitoring = false }: {
  me: Profile; view: View; go: (v: View) => void; signOut: () => void; monitoring?: boolean;
}) {
  return (
    <header className="topbar">
      <span className="brand">eFile (mock)</span>
      <nav>
        <button className={view.kind === "receipts" || view.kind === "receipt" ? "active" : ""} onClick={() => go({ kind: "receipts" })}>Receipt</button>
        <button className={view.kind === "files" || view.kind === "file" ? "active" : ""} onClick={() => go({ kind: "files" })}>File</button>
        <button className={view.kind === "search" ? "active" : ""} onClick={() => go({ kind: "search" })}>Search</button>
        <button className={view.kind === "review" ? "active" : ""} onClick={() => go({ kind: "review" })}>OCR review</button>
        {monitoring && <button className={view.kind === "monitor" ? "active" : ""} onClick={() => go({ kind: "monitor" })}>Monitoring</button>}
        <span className="disabled" title="Not in this sandbox slice">Draft · Dispatch · Settings</span>
      </nav>
      <span className="who">
        {me.name.split(" — ")[0]} · {me.post}
        <button className="link" onClick={signOut}>Sign out</button>
      </span>
    </header>
  );
}
