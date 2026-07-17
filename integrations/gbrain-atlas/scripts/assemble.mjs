import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const openclaw = join(root, "..", "openclaw-atlas");
const cognitive = join(root, "..", "cognitive-service");
for (const generated of ["vendor", "service"]) {
  rmSync(join(root, generated), { recursive: true, force: true });
  mkdirSync(join(root, generated), { recursive: true });
}
const clientSource = readFileSync(join(openclaw, "src", "cognitive-client.ts"), "utf8");
const clientOutput = ts.transpileModule(clientSource, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    target: ts.ScriptTarget.ES2023,
  },
  fileName: "cognitive-client.ts",
}).outputText;
writeFileSync(join(root, "vendor", "cognitive-client.js"), clientOutput);
for (const name of ["server.py", "service_core.py", "schema.sql"]) {
  cpSync(join(cognitive, name), join(root, "service", name));
}
