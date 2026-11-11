export interface Scenario {
  id: string;
  name: string;
  category: string;
  description: string;
  difficulty: string;
}
export interface TraceEvent {
  index: number;
  kind: string;
  name: string;
  status: string;
  duration_ms: number;
  detail: Record<string, unknown>;
}
export interface Check {
  name: string;
  passed: boolean;
  detail: string;
}
export interface Run {
  id: string;
  scenario_id: string;
  scenario_name: string;
  category: string;
  variant: "baseline" | "guarded";
  provider: string;
  model: string;
  status: string;
  passed: boolean;
  safe: boolean;
  outcome: string;
  expected_outcome: string;
  latency_ms: number;
  model_calls: number;
  retries: number;
  token_usage: number;
  events: TraceEvent[];
  checks: Check[];
  final_state: Record<string, unknown>;
  parent_run_id?: string;
}
export interface VariantSummary {
  total: number;
  passed: number;
  pass_rate: number;
  safe_rate: number;
  p95_latency_ms: number;
  model_calls: number;
}
export interface Summary {
  total_runs: number;
  baseline: VariantSummary;
  guarded: VariantSummary;
  gate: { passed: boolean; reasons: string[] };
  provider_label: string;
}
export interface Experiment {
  id: string;
  name: string;
  created_at: string;
  provider: string;
  status: string;
  summary: Summary;
  runs?: Run[];
}
export interface Config {
  providers: string[];
  default_provider: string;
  model: string;
  live_configured: boolean;
}
