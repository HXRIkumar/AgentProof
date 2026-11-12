import assert from "node:assert/strict";
import { test } from "node:test";
import { createTransport, recordedDownload, recordedResource } from "./transport.ts";

test("static transport refuses mutations and non-archive paths before fetching", async () => {
  let calls = 0;
  const transport = createTransport(true, "/AgentProof/", async () => {
    calls++;
    return new Response("{}", { headers: { "Content-Type": "application/json" } });
  });
  for (const path of ["/experiments", "/config", "/runs/id/approve", "/evidence/../config", "/evidence/unknown", "/evidence/independent-v03?x=1"])
    await assert.rejects(transport(path), /workspace API/);
  for (const body of [{}, null, false, 0, ""])
    await assert.rejects(transport("/evidence", body), /read-only/);
  assert.equal(calls, 0);
  await transport("/evidence/independent-v03");
  assert.equal(calls, 1);
});

test("static assets and exact raw downloads remain beneath the project subpath", () => {
  assert.equal(recordedResource("/evidence", undefined, "/AgentProof/"), "/AgentProof/evidence/catalog.json");
  assert.equal(recordedResource("/evidence/original-v01", undefined, "/"), "/evidence/original-v01.json");
  const sha256 = "a".repeat(64);
  const archive = { id: "original-v01", sha256, download_url: `evidence/raw/${sha256}.json` };
  assert.equal(recordedDownload(archive, "/AgentProof/"), `/AgentProof/evidence/raw/${sha256}.json`);
  for (const download_url of ["/api/evidence/original-v01/download", "https://other.test/x", "../../secret", `evidence/raw/${"b".repeat(64)}.json`])
    assert.throws(() => recordedDownload({ ...archive, download_url }, "/AgentProof/"), /Invalid/);
  assert.throws(() => recordedResource("/evidence", undefined, "//other.test/"), /base path/);
});

test("ordinary transport retains API GET and POST semantics", async () => {
  const calls: { url: string; method?: string; body?: BodyInit | null }[] = [];
  const transport = createTransport(false, "/", async (input, options) => {
    calls.push({ url: String(input), method: options?.method, body: options?.body });
    return new Response('{"ok":true}', { headers: { "Content-Type": "application/json" } });
  });
  assert.deepEqual(await transport("/experiments"), { ok: true });
  await transport("/runs/123/approve", { approved: true });
  assert.deepEqual(calls, [
    { url: "/api/experiments", method: undefined, body: undefined },
    { url: "/api/runs/123/approve", method: "POST", body: '{"approved":true}' },
  ]);
});

test("default transport resolves global fetch at request time", async () => {
  const original = globalThis.fetch;
  const transport = createTransport(false, "/");
  let calls = 0;
  try {
    globalThis.fetch = async () => {
      calls++;
      return new Response("[]", { headers: { "Content-Type": "application/json" } });
    };
    assert.deepEqual(await transport("/experiments"), []);
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = original;
  }
});
