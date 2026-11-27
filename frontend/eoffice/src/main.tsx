import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// self-hosted type (no font CDN: the pages' CSP allows 'self' only); Latin subset, used weights
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-serif/latin-400.css";
import "@fontsource/ibm-plex-serif/latin-600.css";
// Telugu and Hindi, self-hosted the same way
import "@fontsource/noto-sans-telugu/telugu-400.css";
import "@fontsource/noto-sans-telugu/telugu-600.css";
import "@fontsource/noto-sans-devanagari/devanagari-400.css";
import "@fontsource/noto-sans-devanagari/devanagari-600.css";
import { App } from "./App";
import { startTranslator } from "./i18n";
import "./styles.css";

startTranslator();
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
