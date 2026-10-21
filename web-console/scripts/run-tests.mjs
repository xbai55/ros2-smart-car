import { build } from "esbuild";
import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

// Resolve from this script rather than the caller's working directory.
const consoleRoot = fileURLToPath(new URL("../", import.meta.url));
const repositoryRoot = fileURLToPath(new URL("../../", import.meta.url));
const testRoot = join(consoleRoot, "tests");
const outputRoot = join(repositoryRoot, "output", "web-console-tests");
const testNames = readdirSync(testRoot).filter(name => name.endsWith(".test.ts")).sort();
if (!testNames.length) throw new Error("No frontend tests found");

await build({
  entryPoints: testNames.map(name => join(testRoot, name)),
  bundle: true,
  platform: "node",
  format: "esm",
  outdir: outputRoot,
  outExtension: { ".js": ".mjs" },
});

// UI source checks intentionally read web-console/... relative to the repository.
// Use explicit bundles so a removed test cannot survive in the output directory.
const result = spawnSync(process.execPath, ["--test", ...testNames.map(name => join(outputRoot, name.replace(/\.ts$/, ".mjs")))], {
  cwd: repositoryRoot,
  stdio: "inherit",
});
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
