export type AnswerStrategy = "baseline" | "validated" | "adaptive";
export type AnswerTask = "qa" | "extraction";
export type AnswerSource = { id: string; title: string; text: string };
export type AnswerCheck = { name: string; passed: boolean; detail: string };
export type AnswerCitation = { source_id: string; quote: string };
export type AnswerUsage = {
  calls: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  known: boolean;
  actual_calls?: number;
  reused_calls?: number;
  actual_total_tokens?: number | null;
  paid_calls?: number;
  actual_paid_calls?: number;
  estimated_cost_usd?: number | null;
  accounted_cost_usd?: number | null;
  actual_accounted_cost_usd?: number | null;
  cost_known?: boolean;
  cost_label?: string;
};
export type AnswerProviderMetadata = {
  model?: string;
  critic_model?: string;
  generator_provider?: string;
  critic_provider?: string;
};
export type AnswerRuntimeMetadata = {
  provider?: AnswerProviderMetadata;
  escalate_final?: boolean;
  escalation_available?: boolean;
};
export type AnswerBudgetSnapshot = {
  ledger_id?: string;
  accounted_usd?: number;
  reported_usage_estimate_usd?: number;
  unresolved_reservations?: number;
};
export type AnswerCritic = {
  supported: boolean;
  responsive: boolean;
  answerable: boolean;
  feedback: string;
};
export type AnswerAttempt = {
  index: number;
  answer: string;
  data: unknown;
  abstained: boolean;
  citations: AnswerCitation[];
  checks: AnswerCheck[];
  critic: AnswerCritic | null;
  latency_ms: number;
  usage: AnswerUsage;
  feedback: string;
  output_text?: string;
  route?: "draft" | "critic_escalation";
  escalation_reason?: string | null;
  generation?: { model?: string };
};
export type AnswerResult = {
  id: string;
  created_at: string;
  task: AnswerTask;
  strategy: AnswerStrategy;
  question: string;
  status: "accepted" | "abstained" | "failed" | "error";
  answer: string;
  data: unknown;
  abstained: boolean;
  citations: AnswerCitation[];
  quality: { score: number; checks: AnswerCheck[]; label: string };
  attempts: AnswerAttempt[];
  cache: { status: string; similarity: number | null };
  usage: AnswerUsage;
  latency_ms: number;
  model: string;
  critic_model?: string;
  generator_provider?: string;
  critic_provider?: string;
  source_hash: string;
  config_hash: string;
  sources?: AnswerSource[];
  error?: string | { message?: string };
  schema?: Record<string, unknown> | null;
  final_attempt_index?: number | null;
  retrieval?: {
    method: string;
    selected: {
      source_id: string;
      title: string;
      score: number;
      text: string;
    }[];
  };
};
export type AnswerConfig = {
  configured: boolean;
  model: string;
  embedding_model: string | null;
  strategies: AnswerStrategy[];
  max_attempts: number;
  provider_kind: string;
};
export type AnswerGrade = {
  correct: boolean;
  exact_match: number | null;
  token_f1: number | null;
  schema_valid: boolean | null;
  field_accuracy: number | null;
};
export type AnswerTrial = {
  case_id: string;
  task: AnswerTask;
  category: string;
  question: string;
  strategy: AnswerStrategy;
  result: AnswerResult;
  grade: AnswerGrade;
  initial_grade: AnswerGrade;
  reference_answers?: string[];
  case?: { gold?: { answers?: string[]; data?: unknown } };
};
export type StrategyMetrics = {
  trials: number;
  correct: number;
  success_rate: number | null;
  exact_match: number | null;
  token_f1: number | null;
  field_accuracy: number | null;
  schema_valid_rate: number | null;
  recovered: number;
  initial_failures: number;
  recovery_rate: number | null;
  task_recovered?: number;
  initial_task_failures?: number;
  task_recovery_rate?: number | null;
  regressed: number;
  initial_successes: number;
  regression_rate: number | null;
  accepted: number;
  accepted_incorrect: number;
  false_accept_rate: number | null;
  retries_per_query: number | null;
  calls_per_query: number | null;
  total_tokens: number | null;
  tokens_per_correct: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  estimated_cost_usd?: number | null;
  accounted_cost_usd?: number | null;
  cost_known?: boolean;
  cost_per_correct_usd?: number | null;
};
export type AnswerSummary = {
  complete: boolean;
  planned_trials: number;
  finished_trials: number;
  strategies: Partial<Record<AnswerStrategy, StrategyMetrics>>;
  comparisons: {
    reference: AnswerStrategy;
    candidate: AnswerStrategy;
    paired_cases: number;
    success_delta: number | null;
    success_delta_ci95: [number, number] | null;
    token_f1_delta: number | null;
    token_f1_delta_ci95: [number, number] | null;
  }[];
};
export type AnswerReport = {
  id: string;
  title: string;
  model: string;
  created_at: string;
  status: string;
  suite: { sha256: string; split: string; case_count: number };
  configuration: Record<string, unknown> & {
    runtime?: AnswerRuntimeMetadata;
  };
  trials: AnswerTrial[];
  summary: AnswerSummary;
  actual_usage?: {
    calls: number;
    total_tokens: number | null;
    usage_known: boolean;
    shared_initial_generations: number;
    estimated_cost_usd?: number | null;
    accounted_cost_usd?: number | null;
    cost_known?: boolean;
  };
  hosted_experiment?: {
    mode?: string;
    budget_before?: AnswerBudgetSnapshot;
    budget_after?: AnswerBudgetSnapshot;
    cost_note?: string;
  };
};
export type AnswerReportEntry = Pick<
  AnswerReport,
  "id" | "title" | "model" | "created_at" | "summary"
>;
export type CacheMeasurement = {
  result: AnswerResult;
  end_to_end_ms: number;
  exact_match: number;
  token_f1: number;
  correct: boolean;
};
export type CacheReportSummary = {
  cold_requests: number;
  exact_replay_requests: number;
  exact_hits: number;
  exact_answer_matches: number;
  exact_hit_rate: number | null;
  paired_cold_requests: number;
  cold_p50_ms: number | null;
  warm_p50_ms: number | null;
  p50_exact_replay_speedup: number | null;
  semantic_queries: number;
  semantic_hits: number;
  semantic_false_hits: number;
  semantic_false_hit_rate: number | null;
  semantic_total_correct: number;
  rejected_candidates: number;
  actual_calls: number;
  tokens: number | null;
  usage_known: boolean;
};
export type CacheReport = {
  format: string;
  status: string;
  created_at: string;
  suite_sha256: string;
  configuration: Record<string, unknown> & AnswerRuntimeMetadata;
  scope: string;
  summary: CacheReportSummary;
  groups: {
    id: string;
    cold: CacheMeasurement;
    replays: CacheMeasurement[];
    queries: (CacheMeasurement & {
      kind: string;
      reuse_expected: boolean;
      references: string[];
    })[];
  }[];
};
export type CacheReportEntry = {
  id: string;
  title: string;
  model: string;
  created_at: string;
  summary: CacheReportSummary;
};
