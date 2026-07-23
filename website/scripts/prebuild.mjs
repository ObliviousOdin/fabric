#!/usr/bin/env node
// Runs website/scripts/extract-skills.py and generate-llms-txt.py before
// docusaurus build/start so that:
//   - website/static/api/skills.json (lazy-fetched by src/pages/skills/index.tsx)
//   - website/static/api/skills-meta.json (sidecar metadata for the Skills Hub)
//   - website/static/llms.txt (agent-friendly short docs index)
//   - website/static/llms-full.txt (full docs concat for LLM context)
//   - website/static/api/runtime-surfaces.json + the matching reference page
// all exist without contributors remembering to run Python scripts manually.
// CI workflows still run the extraction explicitly, which is a no-op duplicate
// but matches their historical behaviour.
//
// We also try to pull a fresh copy of skills-index.json (the unified
// multi-source catalog) from the live docs site if it's not already on disk.
// That way local `npm run build` doesn't have to wait on
// scripts/build_skills_index.py crawling every skill source — which takes
// several minutes and burns GitHub API quota — but still gets the same
// 2000+ external skills the deployed site has.
//
// If python3 or its deps (pyyaml) aren't available on the local machine, we
// fall back to writing an empty skills.json so `npm run build` still
// succeeds — the Skills Hub page just shows an empty state, and llms.txt
// generation is skipped. CI always has the deps installed, so production
// deploys get real data.

import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync, readFileSync, existsSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { resolvePythonRuntime } from "./python-runtime.mjs";
import { writeLatestDesktopRelease } from "./latest-desktop-release.mjs";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const websiteDir = resolve(scriptDir, "..");
const repoDir = resolve(websiteDir, "..");
const pythonCommand = resolvePythonRuntime({ repoDir });
const extractScript = join(scriptDir, "extract-skills.py");
const llmsScript = join(scriptDir, "generate-llms-txt.py");
const cronBlueprintsScript = join(scriptDir, "extract-automation-blueprints.py");
const docsSyncScript = join(repoDir, "scripts", "docs_sync.py");
const skillDocsScript = join(scriptDir, "generate-skill-docs.py");
const outputFile = join(websiteDir, "static", "api", "skills.json");
const unifiedIndexFile = join(websiteDir, "static", "api", "skills-index.json");
const latestReleaseFile = join(
  websiteDir,
  "static",
  "api",
  "latest-release.json",
);
const UNIFIED_INDEX_URL =
  "https://obliviousodin.github.io/fabric/api/skills-index.json";
const UNIFIED_INDEX_MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24h

function readSkillsArray(path) {
  if (!existsSync(path)) return null;
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8"));
    const skills = Array.isArray(parsed) ? parsed : parsed?.skills;
    return Array.isArray(skills) ? skills : null;
  } catch {
    return null;
  }
}

function hasPopulatedSkillsIndex() {
  const skills = readSkillsArray(unifiedIndexFile);
  return Boolean(skills?.length);
}

function writeEmptyFallback(reason) {
  const existing = readSkillsArray(outputFile);
  if (existing?.length) {
    console.warn(
      `[prebuild] extract-skills.py skipped (${reason}); preserving ` +
        `the existing skills.json (${existing.length} skills).`,
    );
    return;
  }
  mkdirSync(dirname(outputFile), { recursive: true });
  writeFileSync(outputFile, "[]\n");
  console.warn(
    `[prebuild] extract-skills.py skipped (${reason}); wrote empty skills.json. ` +
      `Install python3 + pyyaml locally for a populated Skills Hub page.`,
  );
}

function runPython(script, label, args = []) {
  if (!existsSync(script)) {
    console.warn(`[prebuild] ${label} skipped (script missing)`);
    return false;
  }
  if (!pythonCommand) {
    console.warn(`[prebuild] ${label} skipped (Python 3.11-3.13 not found)`);
    return false;
  }
  const r = spawnSync(pythonCommand, [script, ...args], {
    stdio: "inherit",
    cwd: websiteDir,
  });
  if (r.status !== 0) {
    console.warn(`[prebuild] ${label} exited with status ${r.status}`);
    return false;
  }
  return true;
}

async function ensureUnifiedIndex() {
  // If we have a recent copy on disk, trust it.
  if (hasPopulatedSkillsIndex()) {
    try {
      const age = Date.now() - statSync(unifiedIndexFile).mtimeMs;
      if (age < UNIFIED_INDEX_MAX_AGE_MS) {
        return true;
      }
      console.log(
        `[prebuild] skills-index.json is ${(age / 3600000).toFixed(1)}h old; ` +
          `refreshing from ${UNIFIED_INDEX_URL}`,
      );
    } catch {
      // fall through to re-fetch
    }
  }

  try {
    const resp = await fetch(UNIFIED_INDEX_URL, {
      headers: { accept: "application/json" },
    });
    if (!resp.ok) {
      console.warn(
        `[prebuild] skills-index.json fetch returned HTTP ${resp.status}; ` +
          `using local copy if any`,
      );
      return hasPopulatedSkillsIndex();
    }
    const text = await resp.text();
    // Sanity check: must be valid JSON with a skills array
    try {
      const parsed = JSON.parse(text);
      if (!parsed || !Array.isArray(parsed.skills)) {
        console.warn(
          "[prebuild] skills-index.json from live site has no skills array; ignoring",
        );
        return hasPopulatedSkillsIndex();
      }
    } catch (e) {
      console.warn(`[prebuild] skills-index.json from live site is not valid JSON: ${e}`);
      return hasPopulatedSkillsIndex();
    }
    mkdirSync(dirname(unifiedIndexFile), { recursive: true });
    writeFileSync(unifiedIndexFile, text);
    console.log(
      `[prebuild] downloaded skills-index.json from ${UNIFIED_INDEX_URL} ` +
        `(${(text.length / 1024).toFixed(0)} KB)`,
    );
    return true;
  } catch (e) {
    console.warn(`[prebuild] skills-index.json fetch failed: ${e}`);
    return hasPopulatedSkillsIndex();
  }
}

function writeSkillsIndexFallback() {
  if (hasPopulatedSkillsIndex() || !existsSync(outputFile)) return;
  try {
    const skills = readSkillsArray(outputFile);
    if (!Array.isArray(skills)) throw new Error("skills.json is not an array");
    const sources = {};
    for (const skill of skills) {
      const source = skill?.source || "unknown";
      sources[source] = (sources[source] || 0) + 1;
    }
    const index = {
      version: 1,
      generated_at: new Date().toISOString(),
      skill_count: skills.length,
      sources,
      skills,
    };
    mkdirSync(dirname(unifiedIndexFile), { recursive: true });
    writeFileSync(unifiedIndexFile, `${JSON.stringify(index, null, 2)}\n`);
    console.log(
      `[prebuild] wrote local skills-index.json fallback (${skills.length} skills)`,
    );
  } catch (error) {
    console.warn(`[prebuild] could not write bundled skills index: ${error}`);
  }
}

// 0) Pull unified index if we don't have a fresh one.
await ensureUnifiedIndex();

// 0b) Snapshot the newest GitHub Release that actually carries desktop assets.
// The download page refreshes client-side, but this build-time layer works
// offline/without JavaScript and is refreshed by the twice-daily Pages build.
await writeLatestDesktopRelease({ outputFile: latestReleaseFile });

// 1) skills.json — required for the Skills Hub page.
if (!existsSync(extractScript)) {
  writeEmptyFallback("extract script missing");
} else if (!pythonCommand) {
  writeEmptyFallback("Python 3.11-3.13 not found");
} else {
  const r = spawnSync(pythonCommand, [extractScript], {
    stdio: "inherit",
    cwd: websiteDir,
  });
  if (r.status !== 0) {
    writeEmptyFallback(`extract-skills.py exited with status ${r.status}`);
  }
}

// The first public deployment has no live index to download. Always provide a
// valid local catalog so the documented /api/skills-index.json route and
// the CLI Skills Hub never start life as a 404.
writeSkillsIndexFallback();

// 2) Per-skill pages, catalogs, and sidebar. The generator also removes
//    generated pages whose source SKILL.md no longer exists.
runPython(skillDocsScript, "generate-skill-docs.py");

// 3) Deterministic runtime registry catalog. CI runs `check` before prebuild;
//    local builds refresh it so the site always reflects the current checkout.
runPython(docsSyncScript, "docs_sync.py generate", ["generate"]);

// 4) llms.txt + llms-full.txt — agent-friendly docs entrypoints. Non-fatal.
runPython(llmsScript, "generate-llms-txt.py");

// 5) automation-blueprints-index.json — Automation Blueprints catalog page. Non-fatal; the page
//    renders an empty state if the generator can't run.
runPython(cronBlueprintsScript, "extract-automation-blueprints.py");
