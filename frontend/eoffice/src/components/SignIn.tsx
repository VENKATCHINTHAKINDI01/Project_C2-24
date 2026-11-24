import {
  Building2,
  ChevronRight,
  Filter,
  Landmark,
  Lock,
  Search,
  ShieldAlert,
  ShieldCheck,
  UserCheck,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Api } from "../api";
import type { Profile } from "../types";

const CLEARANCE_META: Record<
  string,
  { label: string; tone: "secret" | "confidential" | "restricted" | "unclassified"; icon: typeof Lock }
> = {
  SECRET: { label: "Secret", tone: "secret", icon: ShieldAlert },
  CONFIDENTIAL: { label: "Confidential", tone: "confidential", icon: Lock },
  RESTRICTED: { label: "Restricted", tone: "restricted", icon: ShieldCheck },
  UNCLASSIFIED: { label: "Unclassified", tone: "unclassified", icon: UserCheck },
};

const DEPT_NAMES: Record<string, string> = {
  FIN01: "Finance Department",
  GAD01: "General Administration Department",
  ESE01: "School Education Department",
  USD01: "Municipal Admin & Urban Development",
};

/** Simulated sign-in (no Parichay, no password; ADR-0012): pick a mock officer.
 *  Grouped by department, each with post, section, and clearance that determine visibility. */
export function SignIn({ api, onSignIn }: { api: Api; onSignIn: (p: Profile) => void }) {
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filterDept, setFilterDept] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");

  useEffect(() => {
    api
      .profiles()
      .then((r) => setProfiles(r.profiles))
      .catch((e: Error) => setError(e.message));
  }, [api]);

  const departments = useMemo(() => {
    if (!profiles) return [];
    const counts = new Map<string, number>();
    for (const p of profiles) {
      const d = p.department || "Other";
      counts.set(d, (counts.get(d) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [profiles]);

  const filteredProfiles = useMemo(() => {
    if (!profiles) return [];
    const q = searchQuery.trim().toLowerCase();
    return profiles.filter((p) => {
      const matchesDept = filterDept === "ALL" || p.department === filterDept;
      if (!matchesDept) return false;
      if (!q) return true;
      return (
        p.name.toLowerCase().includes(q) ||
        (p.post ?? "").toLowerCase().includes(q) ||
        (p.section ?? "").toLowerCase().includes(q) ||
        (p.department ?? "").toLowerCase().includes(q) ||
        (p.user_id ?? "").toLowerCase().includes(q)
      );
    });
  }, [profiles, filterDept, searchQuery]);

  const grouped = useMemo(() => {
    const m = new Map<string, Profile[]>();
    for (const p of filteredProfiles) {
      const dept = p.department ?? "General";
      m.set(dept, [...(m.get(dept) ?? []), p]);
    }
    return Array.from(m.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [filteredProfiles]);

  const totalCount = profiles?.length ?? 0;
  const filteredCount = filteredProfiles.length;

  return (
    <main className="signin signin-modern">
      {/* Official Government of Andhra Pradesh Header Banner */}
      <div className="signin-emblem-banner">
        <div className="emblem-crest">
          <Landmark size={28} aria-hidden="true" />
        </div>
        <div className="emblem-text">
          <span className="state-name">GOVERNMENT OF ANDHRA PRADESH</span>
          <span className="portal-title">e-Office Sovereign Institutional Memory & Decision Support System</span>
          <span className="portal-sub">Project C2-24 · High-Assurance Statutory Assistant · Asia-South1</span>
        </div>
      </div>

      <div className="signin-hero-card">
        <div className="hero-content">
          <h1>Select Officer Credentials</h1>
          <p className="lede">
            Sign in as an authorized officer to test deterministic statutory boundary enforcement,
            cross-departmental file noting, and citation-backed intelligence. All sandbox data is synthetic.
          </p>
        </div>
        <div className="hero-security-badge">
          <ShieldCheck size={20} className="badge-icon" />
          <div>
            <strong>Deterministic Boundary Guard</strong>
            <p>Access control is verified at every rung, independent of LLM execution.</p>
          </div>
        </div>
      </div>

      {error && (
        <div className="callout-error" role="alert">
          <ShieldAlert size={20} />
          <div>
            <strong>Sandbox service unavailable</strong>
            <p>Could not connect to backend ({error}). Check server status and reload.</p>
          </div>
        </div>
      )}

      {!profiles && !error && (
        <div className="signin-loading">
          <div className="spinner" aria-hidden="true" />
          <p>Loading officer rosters from secure institutional memory…</p>
        </div>
      )}

      {profiles && (
        <>
          {/* Controls: Search bar + Department Filter Pills */}
          <div className="signin-toolbar">
            <div className="signin-search-box">
              <Search size={18} className="search-icon" aria-hidden="true" />
              <input
                type="search"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search officer by name, post, section, or ID (e.g. U01, Section Officer)…"
                aria-label="Filter officers"
              />
              {searchQuery && (
                <button
                  type="button"
                  className="search-clear-btn"
                  onClick={() => setSearchQuery("")}
                  aria-label="Clear search"
                >
                  <X size={16} />
                </button>
              )}
            </div>

            <div className="dept-filter-bar" role="tablist" aria-label="Filter by department">
              <button
                type="button"
                role="tab"
                aria-selected={filterDept === "ALL"}
                className={`dept-tab ${filterDept === "ALL" ? "active" : ""}`}
                onClick={() => setFilterDept("ALL")}
              >
                <span>All Departments</span>
                <span className="count-pill">{totalCount}</span>
              </button>
              {departments.map(([dept, cnt]) => (
                <button
                  key={dept}
                  type="button"
                  role="tab"
                  aria-selected={filterDept === dept}
                  className={`dept-tab ${filterDept === dept} ? "active" : ""`}
                  onClick={() => setFilterDept(dept)}
                >
                  <Building2 size={14} className="dept-icon" aria-hidden="true" />
                  <span>{dept}</span>
                  <span className="count-pill">{cnt}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="results-summary">
            <span>
              Showing <strong>{filteredCount}</strong> of {totalCount} officers
              {filterDept !== "ALL" ? ` in ${DEPT_NAMES[filterDept] ?? filterDept}` : ""}
              {searchQuery ? ` matching "${searchQuery}"` : ""}
            </span>
          </div>

          {filteredProfiles.length === 0 && (
            <div className="signin-empty-state">
              <Filter size={32} className="muted" />
              <p>No officers match your search query "{searchQuery}".</p>
              <button
                type="button"
                className="button-like"
                onClick={() => {
                  setSearchQuery("");
                  setFilterDept("ALL");
                }}
              >
                Reset filters
              </button>
            </div>
          )}

          {grouped.map(([dept, ps]) => (
            <section key={dept} className="dept-group" aria-label={`Department ${dept}`}>
              <div className="dept-group-header">
                <div className="dept-title-wrap">
                  <span className="dept-code">{dept}</span>
                  <h2>{DEPT_NAMES[dept] ?? dept}</h2>
                </div>
                <span className="dept-officer-count">{ps.length} officer{ps.length === 1 ? "" : "s"}</span>
              </div>

              <ul className="profiles profiles-dossier-grid">
                {ps.map((p) => {
                  const clearMeta = CLEARANCE_META[p.clearance ?? ""] ?? {
                    label: p.clearance ?? "Unclassified",
                    tone: "unclassified",
                    icon: ShieldCheck,
                  };
                  const ClearIcon = clearMeta.icon;
                  const initials = p.name
                    .split(" — ")[0]
                    .replace(/\(.*?\)/g, "")
                    .split(/\s+/)
                    .filter(Boolean)
                    .slice(0, 2)
                    .map((w) => w[0])
                    .join("")
                    .toUpperCase();

                  return (
                    <li key={p.user_id} className="profile-item">
                      <button
                        type="button"
                        className="officer-card-btn"
                        onClick={() => onSignIn(p)}
                        title={`Sign in as ${p.name}`}
                      >
                        <div className={`p-avatar tone-${clearMeta.tone}`} aria-hidden="true">
                          {initials}
                        </div>
                        <div className="p-details">
                          <div className="p-header-line">
                            <span className="p-name">{p.name.split(" — ")[0]}</span>
                            <span className="p-id-badge">{p.user_id}</span>
                          </div>
                          <span className="p-post">{p.post}</span>
                          <div className="p-meta-chips">
                            {p.section && (
                              <span className="meta-chip section-chip">
                                Section {p.section}
                              </span>
                            )}
                            <span className={`meta-chip clearance-chip chip-${clearMeta.tone}`}>
                              <ClearIcon size={12} className="chip-icon" />
                              {clearMeta.label}
                            </span>
                          </div>
                        </div>
                        <div className="p-action-arrow">
                          <ChevronRight size={20} className="p-go" aria-hidden="true" />
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </>
      )}
    </main>
  );
}
