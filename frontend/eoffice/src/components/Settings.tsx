import { useEffect, useState, type ReactNode } from "react";
import type { createApi } from "../api";
import type { Me, Preferences } from "../types";

type Api = ReturnType<typeof createApi>;

function Choice<K extends keyof Preferences>({ label, help, name, value, options, set }: {
  label: string; help?: string; name: K; value: Preferences[K];
  options: [Preferences[K], string][]; set: (k: K, v: Preferences[K]) => void;
}) {
  return (
    <fieldset className="setting">
      <legend>{label}</legend>
      {help && <p className="muted">{help}</p>}
      <div className="segmented" role="radiogroup" aria-label={label}>
        {options.map(([v, text]) => (
          <label key={String(v)} className={value === v ? "on" : undefined}>
            <input type="radio" name={String(name)} checked={value === v} onChange={() => set(name, v)} />
            {text}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Toggle({ label, help, checked, onChange }: {
  label: string; help: string; checked: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <label className="setting toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span><strong>{label}</strong><span className="muted">{help}</span></span>
    </label>
  );
}

const Group = ({ title, children }: { title: string; children: ReactNode }) => (
  <section className="settings-group"><h2>{title}</h2>{children}</section>
);

/** The officer's settings (ADR-0041): how the screens look and how the assistant behaves for
 *  them. Post, section, clearance and search scope are shown but set only by the department. */
export function SettingsPage({ api, prefs, monitoring, onSaved }: {
  api: Api; prefs: Preferences; monitoring: boolean; onSaved: (p: Preferences) => void;
}) {
  const [me, setMe] = useState<Me | null>(null);
  const [draft, setDraft] = useState<Preferences>(prefs);
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  useEffect(() => { api.me().then(setMe).catch(() => setMe(null)); }, [api]);
  useEffect(() => setDraft(prefs), [prefs]);
  const set = <K extends keyof Preferences>(k: K, v: Preferences[K]) => { setDraft((d) => ({ ...d, [k]: v })); setState("idle"); };
  const changed = JSON.stringify(draft) !== JSON.stringify(prefs);

  async function save(p: Promise<Preferences>) {
    setState("saving");
    try { onSaved(await p); setState("saved"); } catch { setState("error"); }
  }

  return (
    <main className="page settings">
      <h1>Settings</h1>
      <p className="muted">These settings change how the screens look and how the assistant behaves for you. They follow you to any browser you sign in from. They never change which files or records you can open.</p>

      <Group title="My profile">
        {me ? (
          <dl className="profile">
            <dt>Name</dt><dd>{me.name}</dd>
            <dt>Post</dt><dd>{me.post}</dd>
            <dt>Department</dt><dd>{me.department}</dd>
            <dt>Section</dt><dd>{me.section ?? "—"}</dd>
            <dt>Clearance</dt><dd>{me.clearance}</dd>
            <dt>Search scope</dt><dd>{me.search_scopes.join(", ").toLowerCase().replace(/_/g, " ") || "—"}</dd>
          </dl>
        ) : <p className="muted">Loading your profile…</p>}
        <p className="muted">Set by the department's e-Office administrator. To change your post, section or clearance, ask the administrator.</p>
      </Group>

      <Group title="Display">
        <Choice label="Theme" help="Dark is easier on the eyes in a dim office or late in the day. Match my computer follows your system's own setting."
          name="theme" value={draft.theme} set={set}
          options={[["light", "Light"], ["dark", "Dark"], ["system", "Match my computer"]]} />
        <Choice label="Text size" name="text_size" value={draft.text_size} set={set}
          options={[["normal", "Normal"], ["large", "Large"], ["larger", "Larger"]]} />
        <Choice label="Spacing" help="Compact fits more rows of a register on screen." name="density" value={draft.density} set={set}
          options={[["comfortable", "Comfortable"], ["compact", "Compact"]]} />
        <Choice label="Contrast" name="contrast" value={draft.contrast} set={set}
          options={[["standard", "Standard"], ["high", "High contrast"]]} />
        <Choice label="Dates" help={`Today would show as ${preview(draft.date_style)}.`} name="date_style" value={draft.date_style} set={set}
          options={[["dd-mm-yyyy", "dd-mm-yyyy"], ["dd Mon yyyy", "dd Mon yyyy"]]} />
        <Choice label="Note and letter text" name="note_font" value={draft.note_font} set={set}
          options={[["serif", "Serif (as printed)"], ["sans", "Sans-serif"]]} />
        <Toggle label="Reduce motion" help="Turn off scrolling animations and transitions."
          checked={draft.reduce_motion} onChange={(v) => set("reduce_motion", v)} />
      </Group>

      <Group title="Start and lists">
        <Choice label="After signing in, open" name="landing" value={draft.landing} set={set}
          options={[["inbox", "File inbox"], ["receipts", "Receipt inbox"], ["search", "Search records"],
            ...(monitoring ? [["monitor", "Monitoring"]] as [Preferences["landing"], string][] : [])]} />
        <fieldset className="setting">
          <legend>Mark files as due soon</legend>
          <p className="muted">Files in your inbox due within this many days are highlighted. 0 turns this off.</p>
          <input type="number" min={0} max={30} value={draft.due_soon_days}
            onChange={(e) => set("due_soon_days", Math.max(0, Math.min(30, Number(e.target.value) || 0)))} /> days
        </fieldset>
      </Group>

      <Group title="Assistant">
        <Choice label="Assistant panel on a file" help="Collapsed keeps the notes wide; open the panel when you need it."
          name="assistant_panel" value={draft.assistant_panel} set={set}
          options={[["open", "Open"], ["collapsed", "Collapsed"]]} />
        <Toggle label="Show answers as they are checked" help="Each statement appears once its citation is verified. Off: the whole answer appears at once."
          checked={draft.stream_answers} onChange={(v) => set("stream_answers", v)} />
        <Toggle label="Keyboard shortcuts" help="On a file: Ctrl / ⌘ + K to ask, Ctrl / ⌘ + Enter to insert the latest first-cut note as a Yellow Note (a draft), J / K between flags, ? for the list. Everywhere: / to go to a file; ↑ ↓ or J K to move between rows of a register, Enter to open."
          checked={draft.shortcuts} onChange={(v) => set("shortcuts", v)} />
        <Toggle label="Notices of new orders" help="On the receipt inbox, show which of your open files cite an order that has just arrived."
          checked={draft.show_notices} onChange={(v) => set("show_notices", v)} />
      </Group>

      <Group title="What is recorded">
        <p className="muted">For each question to the assistant, the system records the question's ID, the time, how long the answer took, its outcome and any feedback you give, for the monitoring officer and evaluation. Document text is never written to logs. The assistant only drafts; nothing is saved, signed or sent without you.</p>
      </Group>

      <div className="settings-actions">
        <button className="primary" disabled={!changed || state === "saving"} onClick={() => save(api.savePreferences(draft))}>Save settings</button>
        <button disabled={state === "saving"} onClick={() => save(api.resetPreferences())}>Restore defaults</button>
        {changed && <button className="link" onClick={() => setDraft(prefs)}>Discard changes</button>}
        <span role="status" className="muted">
          {state === "saving" ? "Saving…" : state === "saved" ? "Settings saved." : state === "error" ? "Settings were not saved. Try again." : changed ? "You have unsaved changes." : ""}
        </span>
      </div>
    </main>
  );
}

function preview(s: Preferences["date_style"]): string {
  const t = new Date();
  const dd = String(t.getDate()).padStart(2, "0"), mm = String(t.getMonth() + 1).padStart(2, "0");
  const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][t.getMonth()];
  return s === "dd Mon yyyy" ? `${dd} ${mon} ${t.getFullYear()}` : `${dd}-${mm}-${t.getFullYear()}`;
}
