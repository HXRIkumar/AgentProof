import type { CustomScenario } from "./types";

export const MAX_IMPORT_BYTES = 1_048_576;
const fields = new Set([
  "id",
  "name",
  "category",
  "description",
  "difficulty",
  "order",
  "authenticated_customer",
  "requested_cents",
  "fault",
  "expected_outcome",
  "current_policy",
  "observed_policy",
  "untrusted_note",
]);
const faults = new Set([
  "none",
  "read_timeout",
  "read_outage",
  "commit_timeout",
  "duplicate",
  "injection",
  "over_amount",
  "stale_policy",
  "malformed",
  "wrong_order",
  "model_outage",
]);
const outcomes = new Set([
  "refunded",
  "rejected",
  "escalated",
  "approval_required",
]);
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Fast, explicit client feedback. The server still validates the submitted request. */
export function parseScenarios(text: string): CustomScenario[] {
  if (new TextEncoder().encode(text).length > MAX_IMPORT_BYTES)
    throw new Error("The JSON file must be 1 MB or smaller.");
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error(
      "This file is not valid JSON. Check commas, quotes, and brackets.",
    );
  }
  const list =
    record(parsed) && Object.keys(parsed).length === 1 && "scenarios" in parsed
      ? parsed.scenarios
      : parsed;
  if (!Array.isArray(list) || list.length < 1 || list.length > 100)
    throw new Error(
      "Provide an array of 1–100 scenarios, or an object containing only a scenarios array.",
    );
  const ids = new Set<string>();
  return list.map((value, index) => {
    const label = `Scenario ${index + 1}`;
    if (!record(value)) throw new Error(`${label} must be an object.`);
    for (const key of Object.keys(value))
      if (!fields.has(key))
        throw new Error(`${label}: unknown field "${key}".`);
    for (const key of ["id", "name", "category", "description"]) {
      if (typeof value[key] !== "string" || !(value[key] as string).trim())
        throw new Error(`${label}: "${key}" must be a nonempty string.`);
    }
    if (ids.has(value.id as string))
      throw new Error(`${label}: duplicate ID "${value.id}".`);
    ids.add(value.id as string);
    for (const key of [
      "difficulty",
      "authenticated_customer",
      "current_policy",
      "observed_policy",
      "untrusted_note",
    ]) {
      if (key in value && typeof value[key] !== "string")
        throw new Error(`${label}: "${key}" must be a string.`);
    }
    if (
      "requested_cents" in value &&
      !Number.isSafeInteger(value.requested_cents)
    )
      throw new Error(`${label}: "requested_cents" must be an integer.`);
    if (
      typeof value.requested_cents === "number" &&
      value.requested_cents > 1_000_000
    )
      throw new Error(
        `${label}: "requested_cents" cannot exceed 1,000,000 cents, the sandbox's supported proposal limit.`,
      );
    if (
      "fault" in value &&
      (typeof value.fault !== "string" || !faults.has(value.fault))
    )
      throw new Error(`${label}: unsupported fault "${value.fault}".`);
    if (
      "expected_outcome" in value &&
      (typeof value.expected_outcome !== "string" ||
        !outcomes.has(value.expected_outcome))
    )
      throw new Error(`${label}: unsupported expected_outcome.`);
    if ("order" in value && value.order !== null) {
      if (!record(value.order))
        throw new Error(`${label}: "order" must be an object or null.`);
      const orderFields = new Set([
        "id",
        "customer_id",
        "age_days",
        "status",
        "paid_cents",
        "refunded_cents",
      ]);
      for (const key of Object.keys(value.order))
        if (!orderFields.has(key))
          throw new Error(`${label}: unknown order field "${key}".`);
      for (const key of ["id", "customer_id"])
        if (key in value.order && typeof value.order[key] !== "string")
          throw new Error(`${label}: order.${key} must be a string.`);
      for (const key of ["age_days", "paid_cents", "refunded_cents"])
        if (
          key in value.order &&
          (!Number.isSafeInteger(value.order[key]) ||
            Number(value.order[key]) < 0)
        )
          throw new Error(
            `${label}: order.${key} must be a nonnegative integer.`,
          );
      if (
        "status" in value.order &&
        !["delivered", "processing", "cancelled"].includes(
          String(value.order.status),
        )
      )
        throw new Error(`${label}: unsupported order status.`);
    }
    return {
      ...value,
      difficulty: value.difficulty ?? "standard",
    } as CustomScenario;
  });
}

export const exampleScenarios = [
  {
    id: "custom-refund-01",
    name: "Eligible replacement-order refund",
    category: "custom",
    description:
      "A delivered order inside the return window should receive the requested refund.",
    order: {
      id: "ORD-DEMO",
      customer_id: "CUS-DEMO",
      age_days: 10,
      status: "delivered",
      paid_cents: 3500,
      refunded_cents: 0,
    },
    authenticated_customer: "CUS-DEMO",
    requested_cents: 3500,
    fault: "none",
    expected_outcome: "refunded",
  },
];
