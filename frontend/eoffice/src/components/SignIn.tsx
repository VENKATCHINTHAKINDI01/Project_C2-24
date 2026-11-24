import { ChevronRight, Landmark, Lock, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Api } from "../api";
import type { Profile } from "../types";

const CLEARANCE: Record<string, string> = {
  UNCLASSIFIED: "Unclassified", RESTRICTED: "Restricted", CONFIDENTIAL: "Confidential", SECRET: "Secret",
};

/** How far the officer's e-Office search reaches (sandbox profile, plan §11). */
const SCOPE: Record<string, string> = {
  individual: "Own files",
  section: "Own section",
  section_hierarchy: "Own and subordinate sections",
  department: "Whole department",
};

const isMonitor = (p: Profile) => /^monitoring officer/i.test(p.post);
const shortName = (p: Profile) => p.name.split(" — ")[0];
const initials = (p: Profile) =>
  shortName(p).replace(/\(.*?\)/g, "").replace(/^(Ch|Sri|Smt|Dr)\.\s*/i, "").split(/[\s.]+/)
    .filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

/** The department's name as its own senior posts write it ("Joint Secretary, Finance" → Finance);
 *  the code when no post names it. Read from the sandbox profiles, never invented. */
function departmentName(code: string, ps: Profile[]): string {
  const counts = new Map<string, number>();
  for (const p of ps) {
    const m = /,\s*([^,()]+)$/.exec(p.post);
    if (m && !/government/i.test(m[1])) counts.set(m[1].trim(), (counts.get(m[1].trim()) ?? 0) + 1);
  }
  const best = [...counts.entries()].sort((a, b) => b[1] - a[1])[0];
  return best ? `${best[0]} Department` : code || "Officers";
}

interface Group { key: string; title: string; code: string | null; officers: Profile[] }

/** Simulated sign-in (no Parichay, no password; ADR-0012): pick a mock officer. Grouped by
 *  department in the order of the sandbox seed (junior to senior), each with the post, section,
 *  clearance and search scope that decide what they will see. */
export function SignIn({ api, onSignIn }: { api: Api; onSignIn: (p: Profile) => void }) {
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [find, setFind] = useState("");
  const [only, setOnly] = useState<string>("all");
  useEffect(() => {
    api.profiles().then((r) => setProfiles(r.profiles)).catch((e: Error) => setError(e.message));
  }, [api]);

  const groups = useMemo<Group[]>(() => {
    const byDept = new Map<string, Profile[]>();
    const monitors: Profile[] = [];
    for (const p of profiles ?? []) {
      if (isMonitor(p)) monitors.push(p);
      else byDept.set(p.department ?? "", [...(byDept.get(p.department ?? "") ?? []), p]);
    }
    const out: Group[] = [...byDept.entries()].map(([code, ps]) => (
      { key: code, title: departmentName(code, ps), code: code || null, officers: ps }));
    if (monitors.length) out.push({ key: "monitoring", title: "C2-24 monitoring", code: null, officers: monitors });
    return out;
  }, [profiles]);

  const q = find.trim().toLowerCase();
  const matches = (p: Profile) =>
    !q || [shortName(p), p.post, p.section ?? "", p.department ?? "", p.user_id].some((s) => s.toLowerCase().includes(q));
  const shown = groups
    .filter((g) => only === "all" || g.key === only)
    .map((g) => ({ ...g, officers: g.officers.filter(matches) }))
    .filter((g) => g.officers.length > 0);
  const total = (profiles ?? []).length;

  return (
    <main className="signin">
      <div className="signin-brand">
        <span className="brand-mark" aria-hidden="true"><Landmark size={22} /></span>
        <span><strong>eFile</strong> sandbox<span className="muted"> · C2-24 assistant</span></span>
      </div>
      <h1>Sign in to the eFile sandbox</h1>
      <p className="lede">
        Choose a mock officer. Their post, section, clearance and search scope decide which files and
        records they see, and so what the assistant can use for them. All data here is synthetic.
      </p>
      {error && <p className="error">The sandbox service is not answering ({error}). Start it with <code>make run</code> and reload.</p>}
      {!profiles && !error && <p className="muted">Loading officers…</p>}
      {profiles && (
        <div className="signin-tools">
          <label className="signin-find">
            <Search size={16} aria-hidden="true" />
            <span className="sr-only">Find an officer</span>
            <input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Find by name, post or section" />
          </label>
          <div className="segmented signin-depts" role="radiogroup" aria-label="Department">
            {[{ key: "all", title: "All", n: total }, ...groups.map((g) => ({ key: g.key, title: g.title.replace(/ Department$/, ""), n: g.officers.length }))].map((o) => (
              <label key={o.key} className={only === o.key ? "on" : undefined}>
                <input type="radio" name="dept" checked={only === o.key} onChange={() => setOnly(o.key)} />
                {o.title} <span className="seg-count">{o.n}</span>
              </label>
            ))}
          </div>
        </div>
      )}
      {profiles && shown.length === 0 && <p className="muted">No officer matches “{find}”.</p>}
      {shown.map((g) => (
        <section key={g.key} aria-label={g.title} className="signin-group">
          <h2>
            {g.title}
            {g.code && <span className="dept-code">{g.code}</span>}
            <span className="dept-n">{g.officers.length} {g.officers.length === 1 ? "officer" : "officers"}</span>
          </h2>
          <ul className="profiles">
            {g.officers.map((p) => (
              <li key={p.user_id}>
                <button onClick={() => onSignIn(p)}>
                  <span className="p-avatar" aria-hidden="true">{initials(p)}</span>
                  <span className="p-name">{shortName(p)}</span>
                  <span className="p-post">{p.post}</span>
                  <span className="p-meta">
                    {p.section && <span className="p-chip">Section {p.section}</span>}
                    <span className={`p-chip clr ${(p.clearance ?? "").toLowerCase()}`}>
                      <Lock size={11} aria-hidden="true" />{CLEARANCE[p.clearance ?? ""] ?? p.clearance} clearance
                    </span>
                    {(p.search_scopes ?? []).map((s) => (
                      <span key={s} className="p-chip scope" title="How far this officer's e-Office search reaches">
                        <ShieldCheck size={11} aria-hidden="true" />{SCOPE[s] ?? s}
                      </span>
                    ))}
                  </span>
                  <ChevronRight className="p-go" size={18} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </main>
  );
}
