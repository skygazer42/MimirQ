import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..", "..");
const webRoot = path.resolve(repoRoot, "web");
const scriptPath = path.resolve(repoRoot, "scripts", "export_openapi.py");

function findPythonExe() {
  const candidates = [];

  // Prefer the repo-local venv if present; `pnpm run openapi:export` should work
  // even when the user hasn't activated the venv in their current shell.
  if (process.platform === "win32") {
    candidates.push(path.join(repoRoot, ".venv", "Scripts", "python.exe"));
    candidates.push(path.join(repoRoot, ".venv", "Scripts", "python"));
  } else {
    candidates.push(path.join(repoRoot, ".venv", "bin", "python3"));
    candidates.push(path.join(repoRoot, ".venv", "bin", "python"));
  }

  candidates.push(...(process.platform === "win32"
    ? ["python", "py", "python3"]
    : ["python3", "python", "py"]));

  for (const exe of candidates) {
    const res = spawnSync(exe, ["--version"], { stdio: "ignore" });
    if (res.status !== 0) {
      continue;
    }
    const fastApiCheck = spawnSync(
      exe,
      ["-c", "import importlib.util as u; import sys; sys.exit(0 if u.find_spec('fastapi') else 1)"],
      { stdio: "ignore" }
    );
    if (fastApiCheck.status === 0) {
      return exe;
    }
  }
  return null;
}

const python = findPythonExe();
if (!python) {
  console.error(
    "[openapi-export] Could not find a working Python executable (tried .venv + python3/python/py)."
  );
  process.exit(1);
}

const args = process.argv.slice(2);
const env = { ...process.env, MIMIRQ_OPENAPI_EXPORT: "1" };

const res = spawnSync(python, [scriptPath, ...args], {
  cwd: webRoot,
  env,
  stdio: "inherit",
});

process.exit(res.status ?? 1);
