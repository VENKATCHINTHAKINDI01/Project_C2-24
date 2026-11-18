/** Dates as Indian government offices write them: 12-05-2025 (and 12-05-2025, 16:10). Accepts an
 *  ISO date or date-time; anything else is shown as given. */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export type DateStyle = "dd-mm-yyyy" | "dd Mon yyyy";
let style: DateStyle = "dd-mm-yyyy";
/** The officer's choice in Settings (ADR-0041); applies to every date the screens show. */
export function setDateStyle(s: DateStyle): void { style = s; }

const day = (y: string, m: string, d: string) =>
  style === "dd Mon yyyy" ? `${d} ${MONTHS[Number(m) - 1] ?? m} ${y}` : `${d}-${m}-${y}`;

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? day(m[1], m[2], m[3]) : iso;
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return fmtDate(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  // shown in India Standard Time, whatever the viewer's machine is set to
  const ist = new Date(d.getTime() + (330 + d.getTimezoneOffset()) * 60_000);
  return `${day(String(ist.getFullYear()), p(ist.getMonth() + 1), p(ist.getDate()))}, ${p(ist.getHours())}:${p(ist.getMinutes())}`;
}
