import { useEffect, useState } from "react";
import type { Api } from "../api";
import type { Profile } from "../types";

/** Simulated sign-in: no Parichay, no password — pick a mock officer (ADR-0012). */
export function SignIn({ api, onSignIn }: { api: Api; onSignIn: (p: Profile) => void }) {
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.profiles().then((r) => setProfiles(r.profiles)).catch((e: Error) => setError(e.message));
  }, [api]);
  return (
    <main className="signin">
      <h1>eFile (mock) — sign in</h1>
      <p className="muted">Simulated sign-in for the sandbox. Choose a mock officer.</p>
      {error && <p className="error">Could not reach the sandbox API: {error}. Is <code>make run</code> running?</p>}
      {!profiles && !error && <p className="muted">Loading officers…</p>}
      <ul className="profiles">
        {profiles?.map((p) => (
          <li key={p.user_id}>
            <button onClick={() => onSignIn(p)}>
              <strong>{p.name}</strong>
              <span>{p.post}</span>
            </button>
          </li>
        ))}
      </ul>
    </main>
  );
}
