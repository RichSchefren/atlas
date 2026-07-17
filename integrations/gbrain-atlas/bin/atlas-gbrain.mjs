#!/usr/bin/env node
import { createHash } from "node:crypto";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import {
  CognitiveServiceError,
  ManagedCognitiveClient,
} from "../vendor/cognitive-client.js";

const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

class GBrainToolError extends Error {
  constructor(message, code = "gbrain_tool_error") {
    super(message);
    this.code = code;
  }
}

function option(name, fallback = undefined) {
  const index = process.argv.indexOf(name);
  return index < 0 ? fallback : process.argv[index + 1];
}

function required(name) {
  const value = option(name);
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function integer(name, fallback) {
  const raw = option(name);
  if (raw === undefined && fallback === undefined) return undefined;
  const value = raw === undefined ? fallback : Number(raw);
  if (!Number.isInteger(value)) throw new Error(`${name} must be an integer`);
  return value;
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function resultText(result) {
  return (result.content ?? [])
    .filter((item) => item.type === "text")
    .map((item) => item.text)
    .join("\n");
}

function parseToolResult(result) {
  const text = resultText(result);
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    parsed = text;
  }
  if (result.isError) {
    const code = parsed?.error?.code ?? parsed?.code ?? "gbrain_tool_error";
    const message = parsed?.error?.message ?? parsed?.message ?? text;
    throw new GBrainToolError(String(message), String(code));
  }
  return parsed;
}

async function connectGBrain(brainId) {
  const client = new Client({ name: "atlas-gbrain", version: "0.1.0" }, { capabilities: {} });
  const url = option("--gbrain-url", process.env.GBRAIN_MCP_URL);
  let transport;
  if (url) {
    const token = option("--gbrain-token", process.env.GBRAIN_MCP_TOKEN);
    transport = new StreamableHTTPClientTransport(new URL(url), {
      requestInit: token ? { headers: { Authorization: `Bearer ${token}` } } : undefined,
    });
  } else {
    const command = option("--gbrain-command", process.env.GBRAIN_COMMAND || "gbrain");
    const argsJson = option("--gbrain-args-json", process.env.GBRAIN_ARGS || '["serve"]');
    const args = JSON.parse(argsJson);
    if (!Array.isArray(args) || args.some((item) => typeof item !== "string")) {
      throw new Error("--gbrain-args-json must be a JSON string array");
    }
    const env = Object.fromEntries(
      Object.entries(process.env).filter((entry) => typeof entry[1] === "string"),
    );
    env.GBRAIN_BRAIN_ID = brainId;
    const source = option("--source", process.env.GBRAIN_SOURCE);
    if (source) env.GBRAIN_SOURCE = source;
    transport = new StdioClientTransport({
      command,
      args,
      env,
      stderr: "inherit",
      cwd: option("--gbrain-cwd", process.env.GBRAIN_CWD),
    });
  }
  await client.connect(transport);
  return {
    call: async (name, args = {}) => parseToolResult(await client.callTool({ name, arguments: args })),
    close: async () => {
      await client.close();
      await transport.close();
    },
  };
}

function pageIdentity(page, brainId) {
  const sourceId = String(page.source_id || option("--source", process.env.GBRAIN_SOURCE || "default"));
  const slug = String(page.slug || required("--slug"));
  const identity = { brain_id: brainId, source_id: sourceId, slug };
  return {
    ...identity,
    root_kref: `gbrain-${sha256(canonical(identity)).slice(0, 32)}`,
  };
}

function cognitiveClient(identity) {
  const dataDir = option(
    "--atlas-home",
    process.env.ATLAS_GBRAIN_HOME || join(homedir(), ".atlas", "gbrain"),
  );
  return new ManagedCognitiveClient(
    dataDir,
    `${identity.brain_id}\0${identity.source_id}`,
    option("--python", process.env.ATLAS_PYTHON),
    join(packageRoot, "service"),
    "gbrain",
  );
}

async function cognitiveGet(client, rootKref) {
  try {
    return await client.request("GET", `/v1/items/get?root_kref=${encodeURIComponent(rootKref)}`);
  } catch (error) {
    if (error instanceof CognitiveServiceError && error.code === "not_found") return null;
    throw error;
  }
}

async function getPage(gbrain, slug) {
  return await gbrain.call("get_page", { slug });
}

async function syncPage(page, brainId, requestedConfidence, reason) {
  const identity = pageIdentity(page, brainId);
  const client = cognitiveClient(identity);
  const content = {
    gbrain: {
      brain_id: identity.brain_id,
      source_id: identity.source_id,
      slug: identity.slug,
      page_id: page.id ?? null,
    },
    page_snapshot: {
      title: page.title ?? null,
      type: page.type ?? null,
      frontmatter: page.frontmatter ?? null,
      compiled_truth: page.compiled_truth ?? page.content ?? "",
      timeline: page.timeline ?? "",
    },
  };
  const current = await cognitiveGet(client, identity.root_kref);
  if (!current) {
    const confidence = requestedConfidence ?? 800000;
    const idempotencyKey = `gbrain-create-${sha256(canonical({ identity, content, confidence }))}`;
    const cognitive = await client.request("POST", "/v1/items/create", {
      idempotency_key: idempotencyKey,
      root_kref: identity.root_kref,
      kind: "fact",
      content,
      confidence_ppm: confidence,
      actor: "gbrain",
      evidence: { source: "gbrain.mcp.get_page", page_id: page.id ?? null },
    });
    return { action: "created", identity, cognitive, client };
  }
  const oldConfidence = current.item.confidence_ppm;
  const confidence = requestedConfidence ?? oldConfidence;
  if (canonical(current.current_revision.content) === canonical(content) && confidence === oldConfidence) {
    return { action: "unchanged", identity, cognitive: current, client };
  }
  const intent = {
    root_kref: identity.root_kref,
    content,
    revision_reason: reason || "GBrain page content changed",
    old_confidence_ppm: oldConfidence,
    new_confidence_ppm: confidence,
    actor: "gbrain",
    evidence: { source: "gbrain.mcp.get_page", page_id: page.id ?? null },
    run_cascade: true,
  };
  const idempotencyKey = `gbrain-revise-${sha256(canonical({
    ...intent,
    base_revision_id: current.current_revision.revision_id,
  }))}`;
  const cognitive = await client.request("POST", "/v1/items/revise", {
    idempotency_key: idempotencyKey,
    ...intent,
  });
  return {
    action: "revised",
    identity,
    cognitive,
    proposals: cognitive.cascade?.proposals ?? [],
    client,
  };
}

async function main() {
  const command = process.argv[2];
  if (!command || command === "help" || command === "--help") {
    process.stdout.write("atlas-gbrain <status|put|sync|get|search|depend|audit|forget> [options]\n");
    return;
  }
  const brainId = option("--brain-id", process.env.GBRAIN_ATLAS_BRAIN_ID || "host");
  const gbrain = await connectGBrain(brainId);
  const ownedClients = [];
  try {
    let output;
    if (command === "status") {
      const identity = await gbrain.call("get_brain_identity");
      const scope = {
        brain_id: brainId,
        source_id: option("--source", process.env.GBRAIN_SOURCE || "default"),
      };
      const client = cognitiveClient(scope);
      ownedClients.push(client);
      output = { gbrain: identity, atlas: await client.ensureAvailable(), scope };
    } else if (command === "put") {
      const slug = required("--slug");
      const file = required("--file");
      const content = readFileSync(file, "utf8");
      await gbrain.call("put_page", { slug, content });
      try {
        const synced = await syncPage(
          await getPage(gbrain, slug),
          brainId,
          integer("--confidence-ppm", undefined),
          option("--reason", "GBrain page written through Atlas bridge"),
        );
        ownedClients.push(synced.client);
        output = synced;
      } catch (error) {
        throw new Error(
          `GBrain write succeeded but Atlas synchronization failed. Rerun 'atlas-gbrain sync --slug ${slug}'. Cause: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    } else if (command === "sync") {
      const synced = await syncPage(
        await getPage(gbrain, required("--slug")),
        brainId,
        integer("--confidence-ppm", undefined),
        option("--reason", "GBrain page synchronized"),
      );
      ownedClients.push(synced.client);
      output = synced;
    } else if (command === "get") {
      const page = await getPage(gbrain, required("--slug"));
      const identity = pageIdentity(page, brainId);
      const client = cognitiveClient(identity);
      ownedClients.push(client);
      output = { page, identity, cognitive: await cognitiveGet(client, identity.root_kref) };
    } else if (command === "search") {
      const query = required("--query");
      const limit = integer("--limit", 10);
      const pages = await gbrain.call("search", { query, limit });
      const scope = {
        brain_id: brainId,
        source_id: option("--source", process.env.GBRAIN_SOURCE || "default"),
      };
      const client = cognitiveClient(scope);
      ownedClients.push(client);
      const cognitive = await client.request("POST", "/v1/items/search", { query, limit });
      output = { pages, cognitive };
    } else if (command === "depend") {
      const dependentPage = await getPage(gbrain, required("--dependent-slug"));
      const supportPage = await getPage(gbrain, required("--support-slug"));
      const dependent = pageIdentity(dependentPage, brainId);
      const support = pageIdentity(supportPage, brainId);
      if (dependent.source_id !== support.source_id) {
        throw new Error("Cross-source Atlas dependencies require explicit federation and are refused by this bridge");
      }
      const client = cognitiveClient(dependent);
      ownedClients.push(client);
      if (!(await cognitiveGet(client, dependent.root_kref)) || !(await cognitiveGet(client, support.root_kref))) {
        throw new Error("Both pages must be synchronized before declaring a dependency");
      }
      const dependency = await client.request("POST", "/v1/dependencies", {
        dependent_kref: dependent.root_kref,
        support_kref: support.root_kref,
        strength_ppm: integer("--strength-ppm", 1000000),
      });
      output = { dependent, support, dependency };
    } else if (command === "audit" || command === "forget") {
      const page = await getPage(gbrain, required("--slug"));
      const identity = pageIdentity(page, brainId);
      const client = cognitiveClient(identity);
      ownedClients.push(client);
      if (command === "audit") {
        output = {
          identity,
          audit: await client.request(
            "GET",
            `/v1/items/audit?root_kref=${encodeURIComponent(identity.root_kref)}`,
          ),
        };
      } else {
        output = {
          identity,
          cognitive: await client.request("POST", "/v1/items/forget", {
            root_kref: identity.root_kref,
            proposition: option("--proposition", ""),
            reason: option("--reason", "GBrain user requested Atlas forget"),
            actor: "gbrain",
          }),
          gbrain_page_preserved: true,
        };
      }
    } else {
      throw new Error(`unknown command: ${command}`);
    }
    const serializable = JSON.parse(JSON.stringify(output, (key, value) => key === "client" ? undefined : value));
    process.stdout.write(`${JSON.stringify(serializable)}\n`);
  } finally {
    await Promise.allSettled(ownedClients.map((client) => client.shutdown()));
    await gbrain.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
