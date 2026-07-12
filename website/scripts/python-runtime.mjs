import { join } from "node:path";
import { spawnSync } from "node:child_process";

const VERSION_PROBE = [
  "-c",
  "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)",
];

/** Return Python candidates in preference order, without duplicates. */
export function pythonCandidates({ repoDir, env = process.env, platform = process.platform }) {
  const executable = platform === "win32" ? "python.exe" : "python";
  const venvBin = platform === "win32" ? "Scripts" : "bin";
  const candidates = [];

  if (env.VIRTUAL_ENV) {
    candidates.push(join(env.VIRTUAL_ENV, venvBin, executable));
  }
  candidates.push(
    join(repoDir, ".venv", venvBin, executable),
    join(repoDir, "venv", venvBin, executable),
    "python3",
    "python",
  );

  return [...new Set(candidates)];
}

/** Select the first interpreter in the project's supported Python range. */
export function resolvePythonRuntime({
  repoDir,
  env = process.env,
  platform = process.platform,
  probe = (candidate) =>
    spawnSync(candidate, VERSION_PROBE, { stdio: "ignore" }).status === 0,
  candidates = pythonCandidates({ repoDir, env, platform }),
}) {
  for (const candidate of candidates) {
    try {
      if (probe(candidate)) return candidate;
    } catch {
      // Missing or non-executable candidates are expected during discovery.
    }
  }
  return null;
}
