import { cpSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = join(packageRoot, "..", "cognitive-service");
const targetRoot = join(packageRoot, "service");
rmSync(targetRoot, { force: true, recursive: true });
mkdirSync(targetRoot, { recursive: true });
for (const name of ["server.py", "service_core.py", "schema.sql"]) {
  cpSync(join(sourceRoot, name), join(targetRoot, name));
}
