# Frontend

React + TypeScript (plan §2). Built so far: the **mock e-Office sandbox screens** in `eoffice/` (plan §11, P8; ADR-0012). The officer-facing C2-24 UI outside the sandbox comes later.

## `eoffice/` — mock e-Office sandbox (SYNTHETIC, not NIC e-Office)

Vite + React + TypeScript, plain CSS, Vitest. Every screen shows the mock banner. Sign-in is simulated (pick a mock officer); the API is the FastAPI service.

```bash
make run          # terminal 1: API on :8080
make fe-install   # once (npm ci, pinned versions in package-lock.json)
make fe-dev       # terminal 2: screens on http://localhost:5173
make fe-check     # typecheck + tests + production build
```

Screens: sign-in picker · file list (reach + clearance) · file inner page (notes, drafts, correspondence TOC, movements) with the **C2-24 Assist** panel (pre-send check, local reference, Insert as Yellow Note) · advance search. "Send" runs the pre-send check only; nothing is sent, signed or confirmed. Toolbar items not built yet are disabled and say so.
