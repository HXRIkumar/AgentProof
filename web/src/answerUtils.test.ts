import assert from "node:assert/strict";
import test from "node:test";
import {
  caseChange,
  duration,
  groupCases,
  number,
  percent,
  usd,
  budgetDelta,
} from "./answerUtils.ts";
import type { AnswerReport, AnswerResult, AnswerTrial } from "./answerTypes.ts";

function trial(
  strategy: AnswerTrial["strategy"],
  correct: boolean,
  caseId = "case-1",
): AnswerTrial {
  return {
    case_id: caseId,
    task: "qa",
    category: "answerable",
    question: "When?",
    strategy,
    result: {} as AnswerResult,
    grade: {
      correct,
      exact_match: Number(correct),
      token_f1: Number(correct),
      schema_valid: null,
      field_accuracy: null,
    },
    initial_grade: {
      correct: false,
      exact_match: 0,
      token_f1: 0,
      schema_valid: null,
      field_accuracy: null,
    },
  };
}
const report = (trials: AnswerTrial[]) => ({ trials }) as AnswerReport;

test("missing and nonfinite metrics remain unknown rather than appearing as zero", () => {
  for (const value of [null, undefined, NaN, Infinity]) {
    assert.equal(percent(value), "—");
    assert.equal(number(value), "—");
    assert.equal(duration(value), "—");
  }
  assert.equal(percent(0), "0.0%");
  assert.equal(duration(0), "0 ms");
  assert.equal(percent(0.952), "95.2%");
});

test("case comparison matches IDs across interleaved strategies", () => {
  const rows = groupCases(
    report([
      trial("baseline", false),
      trial("adaptive", false, "case-2"),
      trial("adaptive", true),
      trial("baseline", true, "case-2"),
    ]),
  );
  assert.equal(rows.length, 2);
  assert.equal(caseChange(rows[0]), "recovered");
  assert.equal(caseChange(rows[1]), "regressed");
});

test("incomplete comparisons are never labelled unchanged or recovered", () => {
  const rows = groupCases(
    report([trial("adaptive", true), trial("validated", false, "case-2")]),
  );
  assert.equal(caseChange(rows[0]), "incomplete");
  assert.equal(caseChange(rows[1]), "incomplete");
});

test("API cost never renders missing or tiny positive amounts as zero", () => {
  for (const value of [undefined, null, NaN, Infinity, -1])
    assert.equal(usd(value), "Unknown");
  assert.equal(usd(0), "$0.00");
  assert.equal(usd(0.0000001), "<$0.000001");
  assert.equal(usd(0.00125), "$0.00125");
});

test("study cost requires matching ledger identity and complete monotonic snapshots", () => {
  const before = { ledger_id: "ledger-a", accounted_usd: 0.02 };
  const after = { ledger_id: "ledger-a", accounted_usd: 0.12 };
  assert.ok(
    Math.abs(budgetDelta(before, after, "accounted_usd")! - 0.1) < 1e-10,
  );
  assert.equal(budgetDelta(undefined, after, "accounted_usd"), null);
  assert.equal(
    budgetDelta(before, { ...after, ledger_id: "ledger-b" }, "accounted_usd"),
    null,
  );
  assert.equal(
    budgetDelta(before, { ...after, accounted_usd: 0.01 }, "accounted_usd"),
    null,
  );
  assert.equal(budgetDelta(before, after, "reported_usage_estimate_usd"), null);
});
