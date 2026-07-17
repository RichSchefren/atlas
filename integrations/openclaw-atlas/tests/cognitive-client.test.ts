import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { ManagedCognitiveClient } from "../src/cognitive-client.js";

test("managed client persists cognition and runs dependency reassessment", async () => {
  const root = mkdtempSync(join(tmpdir(), "atlas-openclaw-cognitive-"));
  const scope = "agent-a\0session-a";
  const first = new ManagedCognitiveClient(root, scope);
  try {
    const health = await first.ensureAvailable();
    assert.equal(health.scope_id, first.scopeId);
    assert.equal(health.service_version, "0.1.0");

    await first.request("POST", "/v1/items/create", {
      idempotency_key: "openclaw-test-create-a",
      root_kref: "memory-a",
      kind: "fact",
      content: { text: "The launch date is Friday." },
      confidence_ppm: 800000,
    });
    await first.request("POST", "/v1/items/create", {
      idempotency_key: "openclaw-test-create-b",
      root_kref: "memory-b",
      kind: "belief",
      content: { text: "The launch campaign starts Thursday." },
      confidence_ppm: 700000,
    });
    await first.request("POST", "/v1/dependencies", {
      dependent_kref: "memory-b",
      support_kref: "memory-a",
      strength_ppm: 900000,
    });
    const revised = (await first.request("POST", "/v1/items/revise", {
      idempotency_key: "openclaw-test-revise-a",
      root_kref: "memory-a",
      content: { text: "The launch date moved to Monday." },
      revision_reason: "Calendar changed",
      old_confidence_ppm: 800000,
      new_confidence_ppm: 300000,
      run_cascade: true,
    })) as { cascade?: { proposals?: Array<{ target_kref?: string }> } };
    assert.equal(revised.cascade?.proposals?.some((item) => item.target_kref === "memory-b"), true);
  } finally {
    await first.shutdown();
  }

  const reopened = new ManagedCognitiveClient(root, scope);
  try {
    const persisted = (await reopened.request(
      "GET",
      "/v1/items/get?root_kref=memory-a",
    )) as { current_revision?: { content?: { text?: string } } };
    assert.equal(persisted.current_revision?.content?.text, "The launch date moved to Monday.");
  } finally {
    await reopened.shutdown();
    rmSync(root, { force: true, recursive: true });
  }
});

test("managed client reports a missing Python executable directly", async () => {
  const root = mkdtempSync(join(tmpdir(), "atlas-openclaw-python-error-"));
  const client = new ManagedCognitiveClient(
    root,
    "missing-python-scope",
    "atlas-python-does-not-exist",
  );
  try {
    await assert.rejects(
      client.ensureAvailable(),
      /Could not launch Atlas with atlas-python-does-not-exist/,
    );
  } finally {
    await client.shutdown();
    rmSync(root, { force: true, recursive: true });
  }
});

test("attached clients fail over without crossing cognitive scope", async () => {
  const root = mkdtempSync(join(tmpdir(), "atlas-openclaw-failover-"));
  const owner = new ManagedCognitiveClient(root, "shared-scope");
  const attached = new ManagedCognitiveClient(root, "shared-scope");
  const isolated = new ManagedCognitiveClient(root, "other-scope");
  try {
    await owner.ensureAvailable();
    await attached.ensureAvailable();
    await owner.request("POST", "/v1/items/create", {
      idempotency_key: "openclaw-failover-create",
      root_kref: "failover-memory",
      kind: "fact",
      content: { text: "Owned service survives through attached-client failover." },
      confidence_ppm: 900000,
    });
    await owner.shutdown();
    const recovered = (await attached.request(
      "GET",
      "/v1/items/get?root_kref=failover-memory",
    )) as { current_revision?: { content?: { text?: string } } };
    assert.equal(recovered.current_revision?.content?.text?.includes("failover"), true);
    await assert.rejects(
      isolated.request("GET", "/v1/items/get?root_kref=failover-memory"),
      (error: unknown) =>
        error instanceof Error &&
        "code" in error &&
        (error as { code?: string }).code === "not_found",
    );
  } finally {
    await Promise.allSettled([owner.shutdown(), attached.shutdown(), isolated.shutdown()]);
    rmSync(root, { force: true, recursive: true });
  }
});
