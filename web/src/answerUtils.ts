import type {
  AnswerBudgetSnapshot,
  AnswerAttempt,
  AnswerReport,
  AnswerReportEntry,
  AnswerStrategy,
  AnswerTrial,
} from "./answerTypes";

export const STRATEGIES: AnswerStrategy[] = [
  "baseline",
  "validated",
  "adaptive",
];
export const STRATEGY_LABELS = {
  baseline: "Direct answer",
  validated: "Validate + retry",
  adaptive: "Critique + refine",
};
export function reportLabel(
  entry: Pick<AnswerReportEntry, "id" | "title">,
): string {
  const labels: Record<string, string> = {
    "qwen-local-v1": "Qwen · local draft and critic",
    "qwen-mini-critic-v1": "Qwen draft · mini critic",
    "qwen-mini-cascade-v1": "Qwen draft · mini critic + final escalation",
    "mini-hosted-v1": "GPT-5.4 mini · hosted draft and critic",
    "mini-hosted-repeat-v1": "GPT-5.4 mini · secondary repeat of the same cases",
  };
  return `${labels[entry.id] || entry.title || "Experiment"} · ${entry.id}`;
}
export const ANSWER_RECORDED_ONLY =
  import.meta.env?.VITE_RECORDED_ONLY === "true";
export const percent = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value)
    ? "—"
    : `${(value * 100).toFixed(1)}%`;
export const number = (value: number | null | undefined, digits = 0) =>
  value == null || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString(undefined, { maximumFractionDigits: digits });
export const duration = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value)
    ? "—"
    : value < 1000
      ? `${number(value, 1)} ms`
      : `${number(value / 1000, 2)} s`;
export const usd = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) || value < 0
    ? "Unknown"
    : value === 0
      ? "$0.00"
      : value < 0.000001
        ? "<$0.000001"
        : `$${(value + Number.EPSILON).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`;
export function budgetDelta(
  before: AnswerBudgetSnapshot | undefined,
  after: AnswerBudgetSnapshot | undefined,
  key: "accounted_usd" | "reported_usage_estimate_usd",
): number | null {
  if (!before?.ledger_id || before.ledger_id !== after?.ledger_id) return null;
  const first = before[key],
    last = after[key];
  if (
    first == null ||
    last == null ||
    !Number.isFinite(first) ||
    !Number.isFinite(last) ||
    first < 0 ||
    last < first
  )
    return null;
  return last - first;
}
export const human = (value: string) =>
  value.replaceAll("_", " ").replaceAll("-", " ");
export const date = (value: string) => {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf())
    ? "Unrecorded"
    : parsed.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
};
export function criticFlag(
  attempt: Pick<AnswerAttempt, "critic" | "checks" | "abstained">,
  field: "supported" | "responsive" | "answerable",
): { state: "na" | "pass" | "fail"; value: string; detail: string } {
  const checkName =
    field === "answerable" ? "critic_answerability" : `critic_${field}`;
  const check = attempt.checks.find((item) => item.name === checkName);
  const raw = attempt.critic?.[field];
  if (attempt.abstained && field !== "answerable" && !check) {
    return {
      state: "na",
      value: "N/A",
      detail: `Not scored for this abstention. Raw critic response: ${String(raw)}.`,
    };
  }
  return {
    state: (check ? check.passed : raw) ? "pass" : "fail",
    value: raw ? "Yes" : "No",
    detail: check?.detail || "Raw critic response; no separate check recorded.",
  };
}
export type CaseRow = {
  id: string;
  question: string;
  task: string;
  category: string;
  trials: Partial<Record<AnswerStrategy, AnswerTrial>>;
};
export function groupCases(report: AnswerReport): CaseRow[] {
  const grouped = new Map<string, CaseRow>();
  for (const trial of report.trials) {
    if (!STRATEGIES.includes(trial.strategy)) continue;
    const row = grouped.get(trial.case_id) ?? {
      id: trial.case_id,
      question: trial.question,
      task: trial.task,
      category: trial.category,
      trials: {},
    };
    row.trials[trial.strategy] = trial;
    grouped.set(trial.case_id, row);
  }
  return [...grouped.values()];
}
export function caseChange(
  row: CaseRow,
): "recovered" | "regressed" | "unchanged" | "incomplete" {
  const first = row.trials.baseline,
    last = row.trials.adaptive;
  if (!first || !last) return "incomplete";
  if (!first.grade.correct && last.grade.correct) return "recovered";
  if (first.grade.correct && !last.grade.correct) return "regressed";
  return "unchanged";
}
export async function answerFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  if (ANSWER_RECORDED_ONLY && init?.method && init.method !== "GET")
    throw new Error(
      "This viewer shows recorded experiments. Run Answer Lab locally to generate new answers.",
    );
  if (ANSWER_RECORDED_ONLY && path === "/config")
    return {
      configured: false,
      model: "",
      embedding_model: null,
      strategies: STRATEGIES,
      max_attempts: 3,
      provider_kind: "recorded",
    } as T;
  if (ANSWER_RECORDED_ONLY && path === "/runs") return [] as T;
  const url = ANSWER_RECORDED_ONLY
    ? path === "/reports"
      ? `${import.meta.env.BASE_URL}answers/catalog.json`
      : path.startsWith("/reports/")
        ? `${import.meta.env.BASE_URL}answers/${path.slice("/reports/".length)}.json`
        : path === "/cache-reports"
          ? `${import.meta.env.BASE_URL}answers-cache/catalog.json`
          : path.startsWith("/cache-reports/")
            ? `${import.meta.env.BASE_URL}answers-cache/${path.slice("/cache-reports/".length)}.json`
            : ""
    : `/api/answers${path}`;
  if (!url)
    throw new Error("This record is not available in the public viewer.");
  const response = await fetch(url, init);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const message =
      typeof payload?.detail === "string"
        ? payload.detail
        : typeof payload?.error === "string"
          ? payload.error
          : `Request failed (${response.status}).`;
    throw new Error(message);
  }
  return payload as T;
}
export function downloadJson(value: unknown, filename: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename.replace(/[^a-zA-Z0-9._-]/g, "_");
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
