import assert from "node:assert/strict";
import { test } from "node:test";
import {
  exampleScenarios,
  MAX_IMPORT_BYTES,
  parseScenarios,
} from "./scenarioImport.ts";

test("accepts explicit custom scenarios and defaults difficulty", () => {
  const cases = parseScenarios(JSON.stringify(exampleScenarios));
  assert.equal(cases[0].order?.paid_cents, 3500);
  assert.equal(cases[0].difficulty, "standard");
  assert.equal(
    parseScenarios(JSON.stringify({ scenarios: exampleScenarios })).length,
    1,
  );
});
test("rejects malformed, empty, oversized, duplicate and non-scenario files", () => {
  for (const input of [
    "{",
    "[]",
    JSON.stringify({ runs: [] }),
    JSON.stringify([null]),
    JSON.stringify([exampleScenarios[0], exampleScenarios[0]]),
    JSON.stringify(Array(101).fill(exampleScenarios[0])),
    " ".repeat(MAX_IMPORT_BYTES + 1),
  ])
    assert.throws(() => parseScenarios(input));
});
test("checks typed domain fields without forbidding deliberate invalid refund requests", () => {
  for (const patch of [
    { requested_cents: "3" },
    { requested_cents: 3.5 },
    { expected_outcome: "success" },
    { fault: "shell" },
    { surprise: true },
    { name: "" },
    { order: { status: "shipped" } },
    { order: { paid_cents: -1 } },
    { order: { id: 25 } },
  ])
    assert.throws(() =>
      parseScenarios(JSON.stringify([{ ...exampleScenarios[0], ...patch }])),
    );
  assert.equal(
    parseScenarios(
      JSON.stringify([
        {
          ...exampleScenarios[0],
          order: null,
          requested_cents: -5,
          expected_outcome: "rejected",
        },
      ]),
    )[0].requested_cents,
    -5,
  );
});

test("accepts the supported request ceiling and rejects larger requests clearly", () => {
  const input = (requested_cents: number) =>
    JSON.stringify([{ ...exampleScenarios[0], requested_cents }]);
  assert.equal(parseScenarios(input(1_000_000))[0].requested_cents, 1_000_000);
  assert.throws(
    () => parseScenarios(input(1_000_001)),
    /requested_cents.*cannot exceed 1,000,000 cents/,
  );
});
