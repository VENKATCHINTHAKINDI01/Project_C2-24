import type { KeyboardEvent } from "react";

/** Registers (file and receipt lists): ↑ / ↓ or J / K move between rows, Enter opens. */
export function rowKeys(e: KeyboardEvent<HTMLElement>, open: () => void): void {
  const row = e.currentTarget;
  const step = (sib: Element | null) => {
    if (sib instanceof HTMLElement && sib.tabIndex >= 0) { e.preventDefault(); sib.focus(); }
  };
  if (e.key === "Enter") { e.preventDefault(); open(); }
  else if (e.key === "ArrowDown" || e.key === "j") step(row.nextElementSibling);
  else if (e.key === "ArrowUp" || e.key === "k") step(row.previousElementSibling);
}
