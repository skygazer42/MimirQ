import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

function findPythonExe() {
  const candidates =
    process.platform === "win32"
      ? ["python", "py", "python3"]
      : ["python3", "python", "py"];

  for (const exe of candidates) {
    const res = spawnSync(exe, ["--version"], { stdio: "ignore" });
    if (res.status === 0) {
      return exe;
    }
  }
  return null;
}

const python = findPythonExe();
if (!python) {
  console.error(
    "[openapi-export] Could not find a working Python executable (tried python3/python/py)."
  );
  process.exit(1);
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..", "..");
const webRoot = path.resolve(repoRoot, "web");
const scriptPath = path.resolve(repoRoot, "scripts", "export_openapi.py");

const args = process.argv.slice(2);
const env = { ...process.env, MIMIRQ_OPENAPI_EXPORT: "1" };

const res = spawnSync(python, [scriptPath, ...args], {
  cwd: webRoot,
  env,
  stdio: "inherit",
});

process.exit(res.status ?? 1);

