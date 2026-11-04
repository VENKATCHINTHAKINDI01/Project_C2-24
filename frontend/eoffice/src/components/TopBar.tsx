import type { Profile } from "../types";

export type View = { kind: "files" } | { kind: "file"; computerNo: string } | { kind: "search" };

export function TopBar({ me, view, go, signOut }: {
  me: Profile; view: View; go: (v: View) => void; signOut: () => void;
}) {
  return (
    <header className="topbar">
      <span className="brand">eFile (mock)</span>
      <nav>
        <button className={view.kind !== "search" ? "active" : ""} onClick={() => go({ kind: "files" })}>File</button>
        <button className={view.kind === "search" ? "active" : ""} onClick={() => go({ kind: "search" })}>Search</button>
        <span className="disabled" title="Not in this sandbox slice">Receipt · Draft · Dispatch · Settings</span>
      </nav>
      <span className="who">
        {me.name.split(" — ")[0]} · {me.post}
        <button className="link" onClick={signOut}>Sign out</button>
      </span>
    </header>
  );
}
