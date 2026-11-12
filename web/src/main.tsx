import React from "react";
import ReactDOM from "react-dom/client";
import AnswerLab from "./AnswerLab";

const LegacyApp = React.lazy(async () => {
  await import("./style.css");
  return import("./App");
});

const legacy = window.location.pathname.startsWith("/legacy") ||
  new URLSearchParams(window.location.search).get("workspace") === "legacy";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {legacy ? <React.Suspense fallback={<p>Loading tool-action laboratory…</p>}><LegacyApp /></React.Suspense> : <AnswerLab />}
  </React.StrictMode>,
);
