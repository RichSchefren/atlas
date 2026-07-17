import { rmSync } from "node:fs";

for (const name of ["vendor", "service"]) {
  rmSync(new URL(`../${name}`, import.meta.url), { recursive: true, force: true });
}
