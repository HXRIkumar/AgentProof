import React from "react";
import ReactDOM from "react-dom/client";
import SupportDesk from "./SupportDesk";
const AnswerLab = React.lazy(() => import("./AnswerLab"));

const LegacyApp = React.lazy(async () => {
  await import("./style.css");
  return import("./App");
});

const legacy =
  window.location.pathname.startsWith("/legacy") ||
  new URLSearchParams(window.location.search).get("workspace") === "legacy";
const answers =
  new URLSearchParams(window.location.search).get("workspace") === "answers";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {legacy ? (
      <React.Suspense fallback={<p>Loading tool-action laboratory…</p>}>
        <LegacyApp />
      </React.Suspense>
    ) : answers ? (
      <React.Suspense fallback={<p>Loading answer experiments…</p>}>
        <AnswerLab />
      </React.Suspense>
    ) : (
      <SupportDesk />
    )}
  </React.StrictMode>,
);
