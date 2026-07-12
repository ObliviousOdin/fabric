import assert from "node:assert/strict";
import test from "node:test";
import { pythonCandidates, resolvePythonRuntime } from "./python-runtime.mjs";

test("prefers an active environment, then repository environments", () => {
  const candidates = pythonCandidates({
    repoDir: "/repo",
    env: { VIRTUAL_ENV: "/active" },
    platform: "linux",
  });

  assert.deepEqual(candidates.slice(0, 3), [
    "/active/bin/python",
    "/repo/.venv/bin/python",
    "/repo/venv/bin/python",
  ]);
});

test("uses the first interpreter that satisfies the project version range", () => {
  const visited = [];
  const selected = resolvePythonRuntime({
    repoDir: "/repo",
    candidates: ["python-old", "python-supported", "python-later"],
    probe: (candidate) => {
      visited.push(candidate);
      return candidate === "python-supported";
    },
  });

  assert.equal(selected, "python-supported");
  assert.deepEqual(visited, ["python-old", "python-supported"]);
});

test("returns null when no compatible interpreter is available", () => {
  assert.equal(
    resolvePythonRuntime({
      repoDir: "/repo",
      candidates: ["python-old", "python-too-new"],
      probe: () => false,
    }),
    null,
  );
});
