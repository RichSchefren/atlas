import { existsSync, realpathSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const suppliedRoot = process.argv[2];
if (!suppliedRoot || !existsSync(join(suppliedRoot, "dist", "mcp", "plugin-tools-serve.js"))) {
  throw new Error("usage: node pinned-host-conformance.mjs /path/to/built/openclaw");
}
const root = realpathSync(suppliedRoot);
const sdkRoot = join(root, "node_modules", "@modelcontextprotocol", "sdk", "dist", "esm");
const { Client } = await import(pathToFileURL(join(sdkRoot, "client", "index.js")).href);
const { StdioClientTransport } = await import(
  pathToFileURL(join(sdkRoot, "client", "stdio.js")).href
);
const env = Object.fromEntries(
  Object.entries(process.env).filter((entry) => typeof entry[1] === "string"),
);
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [join(root, "dist", "mcp", "plugin-tools-serve.js")],
  env,
  stderr: "pipe",
});
const stderr = [];
transport.stderr?.on("data", (chunk) => stderr.push(String(chunk)));
const client = new Client({ name: "atlas-openclaw-conformance", version: "1.0.0" });

function outputText(result) {
  if (result.isError) throw new Error(`host tool failed: ${JSON.stringify(result)}`);
  return (result.content ?? [])
    .filter((item) => item.type === "text")
    .map((item) => item.text)
    .join("\n");
}

async function call(name, args) {
  return outputText(await client.callTool({ name, arguments: args }));
}

try {
  await client.connect(transport);
  const listed = await client.listTools();
  const names = new Set(listed.tools.map((tool) => tool.name));
  for (const name of [
    "memory_search",
    "memory_get",
    "memory_store",
    "memory_revise",
    "memory_depend",
    "memory_audit",
    "memory_forget",
  ]) {
    if (!names.has(name)) throw new Error(`missing host tool ${name}`);
  }

  const supportCreated = await call("memory_store", {
    text: "Atlas pinned host proof says the launch is Friday.",
    kind: "fact",
    confidencePpm: 900000,
  });
  const dependentCreated = await call("memory_store", {
    text: "Atlas pinned host proof schedules the campaign on Thursday.",
    kind: "belief",
    confidencePpm: 800000,
  });
  const supportId = supportCreated.match(/openclaw-[a-f0-9]{32}/)?.[0];
  const dependentId = dependentCreated.match(/openclaw-[a-f0-9]{32}/)?.[0];
  if (!supportId || !dependentId) throw new Error("host store did not return cognitive ids");

  await call("memory_depend", {
    dependentMemoryId: dependentId,
    supportMemoryId: supportId,
    strengthPpm: 1000000,
  });
  const revised = await call("memory_revise", {
    memoryId: supportId,
    text: "Atlas pinned host proof says the launch moved to Monday.",
    reason: "Host conformance revision",
    confidencePpm: 200000,
    contradictsPrior: true,
    contradictionReason: "The launch calendar changed.",
  });
  if (!/Ripple produced [1-9][0-9]* reassessment proposals/.test(revised)) {
    throw new Error(`host revision did not prove Ripple reassessment: ${revised}`);
  }
  const audit = await call("memory_audit", { memoryId: supportId });
  if (!audit.includes(`Audit lineage for ${supportId}`)) throw new Error("host audit failed");
  const search = await call("memory_search", { query: "launch moved Monday", limit: 5 });
  if (!search.includes(supportId)) throw new Error("host search did not retrieve revised memory");
  const fetched = await call("memory_get", { memoryId: supportId });
  if (!fetched.includes("moved to Monday")) throw new Error("host get returned stale content");
  await call("memory_forget", {
    memoryId: dependentId,
    proposition: "campaign schedule",
    reason: "Pinned host conformance cleanup",
  });
  process.stdout.write(
    `${JSON.stringify({ host: "openclaw", tools: names.size, supportId, dependentId, ripple: true })}\n`,
  );
} catch (error) {
  const diagnostic = stderr.join("");
  if (diagnostic) process.stderr.write(diagnostic);
  throw error;
} finally {
  await client.close();
  await transport.close();
}
