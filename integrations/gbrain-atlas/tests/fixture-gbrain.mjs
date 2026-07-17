import { readFileSync, writeFileSync } from "node:fs";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

const statePath = process.argv[2];
if (!statePath) throw new Error("state path required");

function state() {
  try {
    return JSON.parse(readFileSync(statePath, "utf8"));
  } catch {
    return { pages: {} };
  }
}

function save(value) {
  writeFileSync(statePath, `${JSON.stringify(value)}\n`);
}

function result(value, isError = false) {
  return {
    content: [{ type: "text", text: JSON.stringify(value) }],
    ...(isError ? { isError: true } : {}),
  };
}

const tools = ["get_brain_identity", "get_page", "put_page", "search"].map((name) => ({
  name,
  description: `fixture ${name}`,
  inputSchema: { type: "object", properties: {} },
}));
const server = new Server(
  { name: "gbrain-fixture", version: "0.42.61.0" },
  { capabilities: { tools: {} } },
);
server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools }));
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const data = state();
  const args = request.params.arguments ?? {};
  if (request.params.name === "get_brain_identity") {
    return result({
      version: "0.42.61.0",
      engine: "fixture",
      page_count: Object.keys(data.pages).length,
      chunk_count: 0,
      fixture_received_brain_id: process.env.GBRAIN_BRAIN_ID ?? null,
    });
  }
  if (request.params.name === "put_page") {
    const slug = String(args.slug);
    data.pages[slug] = {
      id: `page-${slug}`,
      slug,
      source_id: "default",
      compiled_truth: String(args.content),
    };
    save(data);
    return result({ status: "imported", slug });
  }
  if (request.params.name === "get_page") {
    const page = data.pages[String(args.slug)];
    return page
      ? result(page)
      : result({ error: { code: "page_not_found", message: `Page not found: ${args.slug}` } }, true);
  }
  if (request.params.name === "search") {
    const query = String(args.query).toLowerCase();
    return result(Object.values(data.pages).filter((page) => JSON.stringify(page).toLowerCase().includes(query)));
  }
  return result({ error: { code: "unknown_tool", message: request.params.name } }, true);
});
await server.connect(new StdioServerTransport());
