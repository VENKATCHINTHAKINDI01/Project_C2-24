import { FileText, Landmark, Lock, Quote, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Api } from "../api";
import type { Preferences, Profile } from "../types";
import { DisplayControls } from "./DisplayControls";

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

/** Simulated sign-in (no Parichay, no password; ADR-0012, redesigned ADR-0073): choose a department,
 *  select an officer, sign in. Lists every officer the sandbox returns, in seed order (junior to
 *  senior); each shows the post, section, clearance and search scope that decide what they see. */
export function SignIn({ api, onSignIn, size, onSize }: {
  api: Api; onSignIn: (p: Profile) => void;
  size: Preferences["text_size"]; onSize: (s: Preferences["text_size"]) => void;
}) {
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [find, setFind] = useState("");
  const [only, setOnly] = useState<string>("all");
  const [pick, setPick] = useState<string | null>(null);
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
  const chosen = (profiles ?? []).find((p) => p.user_id === pick) ?? null;

  return (
    <div className="si">
      <div className="si-util">
        <a className="si-skip" href="#si-main">Skip to main content</a>
        <DisplayControls size={size} onSize={onSize} />
      </div>
      <header className="si-head">
        <span className="brand-mark" aria-hidden="true"><Landmark size={22} /></span>
        <span className="si-title"><strong>eFile Sandbox</strong><span>Secretariat file movement and noting · C2-24 assistant</span></span>
      </header>
      <main id="si-main" className="si-main">
        <section className="si-brand" aria-label="About">
          <h1>Notes, movement and approval of every file, in one place</h1>
          <p>Create a file, write the note, send it up for orders and close it once the order is issued. The assistant reads only what your post may open.</p>
          <ul>
            <li><FileText size={18} aria-hidden="true" /><span><strong>File and note sheet</strong>Yellow and Green notes, drafts and issued orders</span></li>
            <li><ShieldCheck size={18} aria-hidden="true" /><span><strong>Access by post</strong>Department, section and clearance decide what you see</span></li>
            <li><Quote size={18} aria-hidden="true" /><span><strong>Answers with sources</strong>Every line points to the order or note it came from</span></li>
          </ul>
          <p className="si-sim"><strong>Simulated sign-in.</strong> No password, DSC, eSign or Parichay is used. Pick an officer to see what that post can open.</p>
        </section>
        <section className="si-card" aria-labelledby="si-h">
          <h2 id="si-h">Sign in</h2>
          <p className="muted">Choose your department, then your post.</p>
          {error && <p className="error">The sandbox service is not answering ({error}). Start it with <code>make run</code> and reload.</p>}
          {!profiles && !error && <p className="muted">Loading officers…</p>}
          {profiles && (
            <>
              <div className="si-tabs" role="radiogroup" aria-label="Department">
                {[{ key: "all", title: "All", n: total }, ...groups.map((g) => ({ key: g.key, title: g.title.replace(/ Department$/, ""), n: g.officers.length }))].map((o) => (
                  <label key={o.key} className={only === o.key ? "on" : undefined}>
                    <input type="radio" name="dept" checked={only === o.key} onChange={() => setOnly(o.key)} />
                    {o.title} <span className="seg-count">{o.n}</span>
                  </label>
                ))}
              </div>
              <label className="signin-find">
                <Search size={16} aria-hidden="true" />
                <span className="sr-only">Find an officer</span>
                <input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Find by name, post or section" />
              </label>
              {shown.length === 0 && <p className="muted">{`No officer matches “${find}”.`}</p>}
              <div className="si-list" role="radiogroup" aria-label="Officer">
                {shown.map((g) => (
                  <div key={g.key} className="si-group">
                    <h3>{g.title}{g.code && <span className="dept-code">{g.code}</span>}<span className="dept-n">{`${g.officers.length} ${g.officers.length === 1 ? "officer" : "officers"}`}</span></h3>
                    {g.officers.map((p) => (
                      <label key={p.user_id} className={`si-off${pick === p.user_id ? " on" : ""}`}>
                        <input type="radio" name="officer" checked={pick === p.user_id} onChange={() => setPick(p.user_id)}
                          onDoubleClick={() => onSignIn(p)} />
                        <span className="p-avatar" aria-hidden="true">{initials(p)}</span>
                        <span className="si-off-text">
                          <span className="p-name">{shortName(p)}</span>
                          <span className="p-post">{p.post}</span>
                          <span className="p-meta">
                            {p.section && <span className="p-chip">{`Section ${p.section}`}</span>}
                            <span className={`p-chip clr ${(p.clearance ?? "").toLowerCase()}`}>
                              <Lock size={11} aria-hidden="true" />{`${CLEARANCE[p.clearance ?? ""] ?? p.clearance} clearance`}
                            </span>
                            {(p.search_scopes ?? []).map((sc) => (
                              <span key={sc} className="p-chip scope" title="How far this officer's e-Office search reaches">
                                <ShieldCheck size={11} aria-hidden="true" />{SCOPE[sc] ?? sc}
                              </span>
                            ))}
                          </span>
                        </span>
                      </label>
                    ))}
                  </div>
                ))}
              </div>
              <button type="button" className="primary si-go" disabled={!chosen} onClick={() => chosen && onSignIn(chosen)}>
                {chosen ? `Sign in as ${shortName(chosen)}` : "Select an officer to continue"}
              </button>
            </>
          )}
        </section>
      </main>
    </div>
  );
}
