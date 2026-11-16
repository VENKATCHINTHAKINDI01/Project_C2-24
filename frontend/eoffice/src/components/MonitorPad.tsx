import { useCallback, useEffect, useMemo, useState } from "react";
import type { Api } from "../api";
import type { ActivityRow, Alert, AlertsView, FrequentQuestion, MonitorData, OfficerActivity, Severity } from "../types";
import { BarChart, LineChart, ShareList } from "./Charts";

/** The monitoring officer's pad (ADR-0035). Only a monitoring officer reaches it; the server
 *  decides that and withholds the words of questions asked under a clearance above theirs. */
type Tab = "alerts" | "activity" | "frequent" | "gaps" | "officers" | "slowest" | "feedback" | "cache";
const TABS: [Tab, string][] = [
  ["alerts", "Alerts"], ["activity", "Activity"], ["frequent", "Frequent questions"], ["gaps", "Unanswered"],
  ["officers", "Officers"], ["slowest", "Slowest"], ["feedback", "Feedback"], ["cache", "Cache"],
];
const OUTCOME: Record<string, string> = {
  answered: "Answered", review_needed: "Review needed", no_answer: "No answer",
  not_run: "Not run", denied: "Denied",
};

/** What a signal code or a refused request means, in words (ADR-0036). */
const WHAT: Record<string, string> = {
  instruction_like: "Reads as instructions to the assistant",
  bulk_request: "Bulk / by-restriction request",
  named_unavailable: "Named an order not open to them",
  off_topic: "Outside what the assistant is for",
  question: "Question",
};
const whatOf = (w: string) => WHAT[w] ?? (w.startsWith("assist.") ? `Refused: ${w.slice(7).replace(/[._]/g, " ")}` : w);
const SEV: Record<Severity, string> = { high: "High", medium: "Medium", low: "Low" };
const SEV_ICON: Record<Severity, string> = { high: "▲", medium: "◆", low: "●" };

const pct = (r: number | null | undefined) => (r == null ? "—" : `${Math.round(r * 100)}%`);
const secs = (ms: number | null | undefined) => (ms == null ? "—" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
const when = (iso: string) => new Date(iso).toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

export function MonitorPad({ api }: { api: Api }) {
  const [days, setDays] = useState(14);
  const [data, setData] = useState<MonitorData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("alerts");
  const [auto, setAuto] = useState(true);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setBusy(true);
    api.monitor(days)
      .then((d) => { setData(d); setUpdated(new Date()); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  }, [api, days]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!auto) return;
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [auto, load]);

  if (error && !data) return <main className="page"><p className="error">{error}</p></main>;
  if (!data) return <main className="page"><p className="muted">Loading the monitoring pad…</p></main>;
  const o = data.overview;
  const al = data.alerts;
  const openHigh = al ? al.alerts.filter((a) => a.status === "open" && a.severity === "high").length : 0;
  const openAll = al ? al.alerts.filter((a) => a.status === "open").length : 0;
  const thumbsUp = o.feedback.thumbs_up ?? 0, thumbsDown = o.feedback.thumbs_down ?? 0;

  return (
    <main className="monitor">
      <header className="monitor-head">
        <div>
          <h2>Monitoring · C2-24 Assist</h2>
          <p>Every question, answer time, outcome and feedback since {data.since}. Question words appear only where your clearance covers the officer who asked.</p>
        </div>
        <div className="controls">
          <select aria-label="Window" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[1, 7, 14, 30, 90].map((n) => <option key={n} value={n}>Last {n} day{n > 1 ? "s" : ""}</option>)}
          </select>
          <label className="toggle"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Live (30 s)</label>
          <button onClick={load} disabled={busy}>{busy ? "Refreshing…" : "Refresh"}</button>
          {updated && <span className="stamp">Updated {updated.toLocaleTimeString()}</span>}
        </div>
      </header>
      {data.truncated && <p className="caveat">More records than the pad reads in this window: the newest 5,000 are shown.</p>}
      {error && <p className="error">{error} (showing the last figures)</p>}

      {openHigh > 0 && tab !== "alerts" && (
        <p className="alert-banner" role="status">
          <span aria-hidden="true">▲</span> {openHigh} open high-severity alert{openHigh > 1 ? "s" : ""} to look at.{" "}
          <button className="linklike" onClick={() => setTab("alerts")}>Open alerts</button>
        </p>
      )}
      <section className="kpis" aria-label="Key figures">
        <Kpi label="Open alerts" value={al ? String(openAll) : "—"} note={al ? `${openHigh} high · ${al.by_department.length} department(s)` : "not available"} tone={openHigh ? "warn" : undefined} />
        <Kpi label="Questions" value={String(o.questions)} note={`${o.days.length} active day(s)`} />
        <Kpi label="Answered" value={pct(o.questions ? (o.outcomes.answered ?? 0) / o.questions : null)} note={`${o.outcomes.answered ?? 0} with checked citations`} />
        <Kpi label="No answer" value={pct(o.no_answer_rate)} note="nothing in the authorised records" tone={(o.no_answer_rate ?? 0) > 0.3 ? "warn" : undefined} />
        <Kpi label="Cache hits" value={pct(o.cache_hit_rate)} note={String(data.cache.backend ?? "")} />
        <Kpi label="Median answer" value={secs(o.p50_ms)} note={`90% within ${secs(o.p90_ms)}`} />
        <Kpi label="Feedback" value={`👍 ${thumbsUp} · 👎 ${thumbsDown}`} note={`${(o.feedback.confirmed ?? 0) + (o.feedback.confirmed_edited ?? 0)} notes confirmed`} />
        <Kpi label="Last start" value={o.start.build_seconds != null ? `${o.start.build_seconds} s` : "—"}
          note={o.start.built_at ? `${o.start.warm_start ? "warm start, " : ""}${when(o.start.built_at)}` : "not started yet"} />
      </section>

      <section className="charts">
        <BarChart title="Questions per day" data={o.days.map((d) => ({
          label: d.day.slice(5), value: d.questions,
          detail: `${d.answered} answered · ${d.no_answer} no answer · ${d.cache_hits} from cache`,
        }))} />
        <LineChart title="Answer time per day (seconds)" labels={o.days.map((d) => d.day.slice(5))} series={[
          { name: "Median", cls: "s1", values: o.days.map((d) => (d.p50_ms == null ? null : +(d.p50_ms / 1000).toFixed(1))) },
          { name: "90th percentile", cls: "s2", values: o.days.map((d) => (d.p90_ms == null ? null : +(d.p90_ms / 1000).toFixed(1))) },
        ]} unit=" s" />
        <ShareList title="Outcome" items={Object.entries(o.outcomes).filter(([, n]) => n > 0).map(([k, n]) => [OUTCOME[k] ?? k, n])} />
        <ShareList title="Search step that answered" items={Object.entries(o.answered_by).sort().map(([k, n]) => [k === "none" ? "none (no record)" : k, n])} />
      </section>

      <nav className="tabs" role="tablist">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
            {label}{k === "gaps" && data.gaps.length ? <span className="count">{data.gaps.length}</span> : null}
            {k === "alerts" && openAll ? <span className={`count${openHigh ? " hot" : ""}`}>{openAll}</span> : null}
          </button>
        ))}
      </nav>
      <section className="tab-body">
        {tab === "alerts" && (al ? <Alerts view={al} api={api} onChange={load} /> : <p className="muted">Alerts are not available on this server.</p>)}
        {tab === "activity" && <Activity rows={data.activity} />}
        {tab === "frequent" && <Questions rows={data.frequent} empty="No question asked in this window." />}
        {tab === "gaps" && (
          <>
            <p className="muted">Questions no authorised record answered: candidates for new records, better wording, or access the officer lacks.</p>
            <Questions rows={data.gaps} empty="Every question in this window found an answer." />
          </>
        )}
        {tab === "officers" && <Officers rows={data.officers} />}
        {tab === "slowest" && <Activity rows={data.slowest} compact />}
        {tab === "feedback" && (
          <table className="grid mon">
            <thead><tr><th>When</th><th>Officer</th><th>On</th><th>Action</th><th>Reason</th><th>Edited</th></tr></thead>
            <tbody>
              {data.feedback.map((f, i) => (
                <tr key={i}><td>{when(f.ts)}</td><td>{f.user_id}</td><td>{f.target.replace("_", " ")}</td>
                  <td><span className={`badge ${f.action.includes("down") || f.action === "dismissed" || f.action === "discarded" ? "warn" : "ok"}`}>{f.action.replace("_", " ")}</span></td>
                  <td>{f.reason?.replace("_", " ") ?? "—"}</td><td>{f.edit_share == null ? "—" : pct(f.edit_share)}</td></tr>
              ))}
            </tbody>
          </table>
        )}
        {tab === "cache" && <Cache c={data.cache} />}
      </section>
    </main>
  );
}

function Kpi({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: "warn" }) {
  return (
    <div className={`kpi${tone ? ` ${tone}` : ""}`}>
      <span className="k-label">{label}</span>
      <span className="k-value">{value}</span>
      {note && <span className="k-note">{note}</span>}
    </div>
  );
}

function Question({ q, withheld }: { q: string | null; withheld: boolean }) {
  if (q) return <span className="q">{q}</span>;
  return <span className="withheld" title="Asked under a clearance above yours">{withheld ? "words withheld (clearance)" : "—"}</span>;
}

function toCsv(rows: ActivityRow[]): string {
  const head = ["time", "officer", "role", "department", "question", "outcome", "answered_by", "latency_ms", "cache_hit", "cited", "feedback", "flags"];
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  return [head.join(","), ...rows.map((r) => [r.ts, r.user_id, r.role, r.department, r.question ?? (r.withheld ? "(withheld)" : ""), r.outcome, r.answered_by, r.latency_ms, r.cache_hit, r.cited, r.feedback, (r.flags ?? []).join(" ")].map(esc).join(","))].join("\n");
}

function Activity({ rows, compact = false }: { rows: ActivityRow[]; compact?: boolean }) {
  const [find, setFind] = useState("");
  const [outcome, setOutcome] = useState("");
  const [flagged, setFlagged] = useState(false);
  const shown = useMemo(() => rows.filter((r) =>
    (!outcome || r.outcome === outcome) && (!flagged || !!r.flags?.length) &&
    (!find || `${r.user_id} ${r.role} ${r.department} ${r.question ?? ""}`.toLowerCase().includes(find.toLowerCase()))), [rows, find, outcome, flagged]);
  const download = () => {
    const url = URL.createObjectURL(new Blob([toCsv(shown)], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = "c2-24-activity.csv"; a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <>
      {!compact && (
        <div className="filters">
          <input placeholder="Find an officer, role, department or words…" value={find} onChange={(e) => setFind(e.target.value)} />
          <select aria-label="Outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option value="">All outcomes</option>
            {Object.entries(OUTCOME).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <label className="toggle"><input type="checkbox" checked={flagged} onChange={(e) => setFlagged(e.target.checked)} /> Flagged only</label>
          <button onClick={download} disabled={!shown.length}>Export CSV</button>
          <span className="muted">{shown.length} of {rows.length}</span>
        </div>
      )}
      <table className="grid mon">
        <thead><tr><th>When</th><th>Officer</th><th>Question</th><th>Outcome</th><th>Step</th><th>Time</th><th>Cache</th><th>Cited</th><th>Feedback</th></tr></thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.query_id}>
              <td className="nowrap">{when(r.ts)}</td>
              <td><strong>{r.user_id}</strong><div className="sub">{r.role} · {r.department}{r.section ? ` · ${r.section}` : ""}</div></td>
              <td><Question q={r.question} withheld={r.withheld} />{r.intent && <div className="sub">{r.intent.replace(/_/g, " ")}</div>}
                {r.flags?.length ? <div className="flags">{r.flags.map((f) => <span key={f} className="flag">{whatOf(f)}</span>)}</div> : null}</td>
              <td><span className={`badge ${r.outcome === "answered" ? "ok" : r.outcome === "no_answer" ? "warn" : ""}`}>{OUTCOME[r.outcome] ?? r.outcome}</span></td>
              <td>{r.answered_by ?? "—"}</td>
              <td className={`num${r.latency_ms > 20000 ? " slow" : ""}`}>{secs(r.latency_ms)}</td>
              <td>{r.cache_hit ? "hit" : ""}</td>
              <td className="num">{r.cited}</td>
              <td>{r.feedback ? r.feedback.replace("_", " ") : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {shown.length === 0 && <p className="muted">Nothing to show.</p>}
    </>
  );
}

function Questions({ rows, empty }: { rows: FrequentQuestion[]; empty: string }) {
  if (!rows.length) return <p className="muted">{empty}</p>;
  const top = Math.max(...rows.map((r) => r.times));
  return (
    <table className="grid mon">
      <thead><tr><th>Question</th><th>Asked</th><th>Officers</th><th>Answered</th><th>Avg time</th><th>Last asked</th></tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td><Question q={r.question} withheld={r.withheld} /></td>
            <td className="num"><span className="inline-bar" style={{ width: `${(r.times / top) * 60}px` }} />{r.times}</td>
            <td className="num">{r.officers}</td>
            <td className="num">{pct(r.answered_rate)}</td>
            <td className="num">{secs(r.avg_ms)}</td>
            <td className="nowrap">{when(r.last_asked)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Officers({ rows }: { rows: OfficerActivity[] }) {
  const [key, setKey] = useState<keyof OfficerActivity>("questions");
  const sorted = [...rows].sort((a, b) => (a[key] > b[key] ? -1 : a[key] < b[key] ? 1 : 0));
  const H = ({ k, children }: { k: keyof OfficerActivity; children: string }) => (
    <th className="sortable" aria-sort={key === k ? "descending" : "none"} onClick={() => setKey(k)}>{children}{key === k ? " ▾" : ""}</th>
  );
  if (!rows.length) return <p className="muted">No officer asked anything in this window.</p>;
  return (
    <table className="grid mon">
      <thead><tr><H k="user_id">Officer</H><H k="questions">Questions</H><H k="answered">Answered</H><H k="no_answer">No answer</H><H k="avg_ms">Avg time</H><H k="thumbs_up">👍</H><H k="thumbs_down">👎</H><H k="last_seen">Last seen</H></tr></thead>
      <tbody>
        {sorted.map((r) => (
          <tr key={r.user_id}>
            <td><strong>{r.user_id}</strong><div className="sub">{r.role} · {r.department}</div></td>
            <td className="num">{r.questions}</td><td className="num">{r.answered}</td><td className="num">{r.no_answer}</td>
            <td className="num">{secs(r.avg_ms)}</td><td className="num">{r.thumbs_up}</td><td className="num">{r.thumbs_down}</td>
            <td className="nowrap">{when(r.last_seen)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const CACHE_LABEL: Record<string, string> = {
  backend: "Cache", serving: "Serving answers", reachable: "Reachable", hits: "Hits (this instance)",
  misses: "Misses (this instance)", errors: "Errors", answers: "Saved answers", embeddings: "Saved question vectors",
  used_memory: "Memory used", max_memory: "Memory limit", evicted_keys: "Evicted", connected_clients: "Clients",
  server_hits: "Server hits", server_misses: "Server misses", version: "Server version", ttl_s: "Answer lifetime (s)",
  embedding_hits: "Embedding hits", embedding_misses: "Embedding misses",
};

function Cache({ c }: { c: MonitorData["cache"] }) {
  const redis = String(c.backend ?? "").startsWith("redis");
  const hits = Number(c.hits ?? 0), misses = Number(c.misses ?? 0);
  return (
    <div className="cache">
      <p className="muted">
        {redis
          ? "Answers are shared by every instance (Memorystore). An answer is reused only for officers with the same access, and dropped when a record it cites changes."
          : "Redis (Memorystore) is not connected: answers are cached in this instance's memory only and lost when it restarts."}
      </p>
      <div className="kpis small">
        <div className="kpi"><span className="k-label">Hit rate (this instance)</span><span className="k-value">{hits + misses ? pct(hits / (hits + misses)) : "—"}</span></div>
        {c.serving === false && <div className="kpi warn"><span className="k-label">Status</span><span className="k-value">Not serving</span><span className="k-note">an invalidation failed; restart clears it</span></div>}
      </div>
      <dl className="kv">
        {Object.entries(c).map(([k, v]) => (
          <div key={k}><dt>{CACHE_LABEL[k] ?? k}</dt><dd>{v === null ? "—" : String(v)}</dd></div>
        ))}
      </dl>
    </div>
  );
}

/** Unusual activity across departments (ADR-0036). An alert asks the monitoring officer to look;
 *  it is not a finding, and nothing is done to the officer's access or sent to anyone. */
export function Alerts({ view, api, onChange }: { view: AlertsView; api: Api; onChange: () => void }) {
  const [sev, setSev] = useState<"" | Severity>("");
  const [status, setStatus] = useState<"open" | "all">("open");
  const [dept, setDept] = useState("");
  const [rule, setRule] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const shown = useMemo(() => view.alerts.filter((a) =>
    (!sev || a.severity === sev) && (status === "all" || a.status === "open") &&
    (!dept || a.department === dept) && (!rule || a.rule === rule)), [view, sev, status, dept, rule]);
  const titles = useMemo(() => Object.fromEntries(view.alerts.map((a) => [a.rule, a.title])), [view]);
  const act = (a: Alert, action: "reviewed" | "escalated", reason?: "expected_activity") => {
    setBusy(a.alert_id); setErr(null);
    api.reviewAlert(a.alert_id, action, reason)
      .then(onChange)
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(null));
  };
  return (
    <>
      <p className="muted">
        Unusual activity across departments: repeated requests for records not open to the officer, questions that read as
        instructions to the assistant, bulk requests, attempts to open this pad, unusual volume, off-topic questions and
        after-hours use. An alert asks you to look — it is not a finding against the officer, and the officer is not told.
        <span className="pill">thresholds {view.config_version}: {view.config_status}</span>
      </p>
      {view.by_department.length > 0 && (
        <div className="dept-strip" aria-label="Alerts by department">
          {view.by_department.map((d) => (
            <button key={d.department} className={`dept${dept === d.department ? " on" : ""}`} aria-pressed={dept === d.department}
              onClick={() => setDept(dept === d.department ? "" : d.department)}>
              <strong>{d.department}</strong>
              <span className="sevs">
                {d.high > 0 && <span className="sev high">{SEV_ICON.high} {d.high}</span>}
                {d.medium > 0 && <span className="sev medium">{SEV_ICON.medium} {d.medium}</span>}
                {d.low > 0 && <span className="sev low">{SEV_ICON.low} {d.low}</span>}
              </span>
              <span className="sub">{d.open} open · {d.officers} officer{d.officers > 1 ? "s" : ""}</span>
            </button>
          ))}
        </div>
      )}
      <div className="filters">
        <select aria-label="Severity" value={sev} onChange={(e) => setSev(e.target.value as "" | Severity)}>
          <option value="">All severities</option>
          {(["high", "medium", "low"] as Severity[]).map((s) => <option key={s} value={s}>{SEV[s]}</option>)}
        </select>
        <select aria-label="Kind" value={rule} onChange={(e) => setRule(e.target.value)}>
          <option value="">All kinds</option>
          {Object.entries(view.by_rule).map(([k, n]) => <option key={k} value={k}>{titles[k] ?? k} ({n})</option>)}
        </select>
        <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value as "open" | "all")}>
          <option value="open">Open only</option>
          <option value="all">Open and reviewed</option>
        </select>
        {dept && <button onClick={() => setDept("")}>All departments</button>}
        <span className="muted">{shown.length} of {view.alerts.length}</span>
      </div>
      {err && <p className="error">{err}</p>}
      {shown.length === 0 && <p className="muted">{view.alerts.length ? "No alert matches these filters." : "No unusual activity in this window."}</p>}
      <ul className="alerts">
        {shown.map((a) => (
          <li key={a.alert_id} className={`alert ${a.severity} ${a.status}`}>
            <div className="alert-head">
              <span className={`sev ${a.severity}`}><span aria-hidden="true">{SEV_ICON[a.severity]}</span> {SEV[a.severity]}</span>
              <strong>{a.title}</strong>
              <span className="muted">· {a.count}×</span>
              {a.status !== "open" && <span className="pill">{a.status} by {a.reviewed_by}{a.reviewed_at ? `, ${when(a.reviewed_at)}` : ""}</span>}
            </div>
            <div className="sub">
              <strong>{a.user_id}</strong> · {a.role} · {a.department} · {a.day} · {when(a.first_seen)}{a.first_seen !== a.last_seen ? ` – ${when(a.last_seen)}` : ""}
            </div>
            <details>
              <summary>Show {a.examples.length === a.count ? "" : `latest ${a.examples.length} of `}{a.count}</summary>
              <table className="grid mon">
                <thead><tr><th>When</th><th>What</th><th>Question</th></tr></thead>
                <tbody>
                  {a.examples.map((e, i) => (
                    <tr key={i}><td className="nowrap">{when(e.ts)}</td><td>{whatOf(e.what)}</td>
                      <td>{e.query_id ? <Question q={e.question} withheld={e.withheld} /> : <span className="muted">no question (a page request)</span>}</td></tr>
                  ))}
                </tbody>
              </table>
            </details>
            {a.status === "open" && (
              <div className="alert-actions">
                <button disabled={busy === a.alert_id} onClick={() => act(a, "reviewed")}>Reviewed — nothing further</button>
                <button disabled={busy === a.alert_id} onClick={() => act(a, "reviewed", "expected_activity")}>Expected work</button>
                <button className="danger" disabled={busy === a.alert_id} onClick={() => act(a, "escalated")}>Escalate</button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}
