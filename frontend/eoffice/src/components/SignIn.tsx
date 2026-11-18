import { useEffect, useMemo, useState } from "react";
import type { Api } from "../api";
import type { Profile } from "../types";

const CLEARANCE: Record<string, string> = {
  UNCLASSIFIED: "Unclassified", RESTRICTED: "Restricted", CONFIDENTIAL: "Confidential", SECRET: "Secret",
};

/** Simulated sign-in (no Parichay, no password; ADR-0012): pick a mock officer. Grouped by
 *  department, each with the post, section and clearance that decide what they will see. */
export function SignIn({ api, onSignIn }: { api: Api; onSignIn: (p: Profile) => void }) {
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.profiles().then((r) => setProfiles(r.profiles)).catch((e: Error) => setError(e.message));
  }, [api]);
  const groups = useMemo(() => {
    const m = new Map<string, Profile[]>();
    (profiles ?? []).forEach((p) => m.set(p.department ?? "", [...(m.get(p.department ?? "") ?? []), p]));
    return [...m.entries()];
  }, [profiles]);
  return (
    <main className="signin">
      <h1>Sign in to the eFile sandbox</h1>
      <p className="lede">
        Choose a mock officer. Their post, section and clearance decide which files and records they
        see, and so what the assistant can use for them. All data here is synthetic.
      </p>
      {error && <p className="error">The sandbox service is not answering ({error}). Start it with <code>make run</code> and reload.</p>}
      {!profiles && !error && <p className="muted">Loading officers…</p>}
      {groups.map(([dept, ps]) => (
        <section key={dept} aria-label={dept ? `Department ${dept}` : "Officers"}>
          {dept && <h2>{dept}</h2>}
          <ul className="profiles">
            {ps.map((p) => (
              <li key={p.user_id}>
                <button onClick={() => onSignIn(p)}>
                  <span className="p-name">{p.name.split(" — ")[0]}</span>
                  <span className="p-post">{p.post}</span>
                  <span className="p-meta">
                    {p.section ? `Section ${p.section}, ` : ""}{CLEARANCE[p.clearance ?? ""] ?? p.clearance ?? ""} clearance
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </main>
  );
}
