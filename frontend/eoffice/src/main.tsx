import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// self-hosted type (no font CDN: the pages' CSP allows 'self' only); Latin subset, used weights
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-serif/latin-400.css";
import "@fontsource/ibm-plex-serif/latin-600.css";
import { App } from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
