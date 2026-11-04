export const BANNER_TEXT =
  "MOCK e-OFFICE SANDBOX — simulation for the C2-24 demo · not NIC e-Office · synthetic data";

/** Shown on every screen (plan §11.1, CLAUDE.md §2.4). */
export function Banner() {
  return <div className="banner" role="note">{BANNER_TEXT}</div>;
}
