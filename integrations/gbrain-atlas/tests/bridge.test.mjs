import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

const root = new URL("..", import.meta.url).pathname;
const cli = join(root, "bin", "atlas-gbrain.mjs");
const fixture = join(root, "tests", "fixture-gbrain.mjs");

test("bridge writes GBrain pages and adds Atlas lineage, dependencies, and Ripple", () => {
  const temp = mkdtempSync(join(tmpdir(), "atlas-gbrain-bridge-"));
  const fixtureState = join(temp, "gbrain.json");
  const supportFile = join(temp, "support.md");
  const dependentFile = join(temp, "dependent.md");
  const env = {
    ...process.env,
    ATLAS_GBRAIN_HOME: join(temp, "atlas"),
    GBRAIN_COMMAND: process.execPath,
    GBRAIN_ARGS: JSON.stringify([fixture, fixtureState]),
  };
  const run = (...args) => JSON.parse(execFileSync(process.execPath, [cli, ...args], {
    encoding: "utf8",
    env,
  }));
  try {
    const status = run("status", "--brain-id", "team-brain");
    assert.equal(status.gbrain.selected_brain_id, "team-brain");
    assert.equal(status.scope.brain_id, "team-brain");

    writeFileSync(supportFile, "# Launch\n\nThe launch is Friday.\n");
    writeFileSync(dependentFile, "# Campaign\n\nThe campaign starts Thursday.\n");
    const support = run("put", "--slug", "plans/launch", "--file", supportFile, "--confidence-ppm", "900000");
    const dependent = run("put", "--slug", "plans/campaign", "--file", dependentFile, "--confidence-ppm", "800000");
    assert.equal(support.action, "created");
    assert.equal(dependent.action, "created");

    const dependency = run(
      "depend",
      "--dependent-slug",
      "plans/campaign",
      "--support-slug",
      "plans/launch",
      "--strength-ppm",
      "1000000",
    );
    assert.equal(dependency.dependency.strength_ppm, 1000000);

    writeFileSync(supportFile, "# Launch\n\nThe launch moved to Monday.\n");
    const revised = run(
      "put",
      "--slug",
      "plans/launch",
      "--file",
      supportFile,
      "--confidence-ppm",
      "200000",
      "--reason",
      "Calendar changed",
    );
    assert.equal(revised.action, "revised");
    assert.equal(revised.proposals.length > 0, true);

    const fetched = run("get", "--slug", "plans/launch");
    assert.equal(fetched.page.compiled_truth.includes("moved to Monday"), true);
    assert.equal(
      fetched.cognitive.current_revision.content.page_snapshot.compiled_truth.includes("moved to Monday"),
      true,
    );
    const audit = run("audit", "--slug", "plans/launch");
    assert.equal(audit.audit.lineage.length, 2);
    const search = run("search", "--query", "Monday", "--limit", "5");
    assert.equal(search.pages.length, 1);
    assert.equal(search.cognitive.length, 1);
    const forgotten = run("forget", "--slug", "plans/campaign", "--reason", "test cleanup");
    assert.equal(forgotten.cognitive.deprecated, true);
    assert.equal(forgotten.gbrain_page_preserved, true);
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
});
