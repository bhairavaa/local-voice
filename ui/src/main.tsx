import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { RecordingOverlay } from "./components/RecordingOverlay";
import "./styles/index.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("Root container is missing from index.html");
}

// The shell opens two windows from the same bundle. A query parameter selects which one this
// document is, which avoids a router and a second build for a single indicator.
const isOverlay = new URLSearchParams(window.location.search).get("window") === "overlay";

if (isOverlay) {
  document.body.classList.add("bg-transparent");
}

createRoot(container).render(
  <StrictMode>{isOverlay ? <RecordingOverlay /> : <App />}</StrictMode>,
);
