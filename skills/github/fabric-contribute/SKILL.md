---
name: fabric-contribute
description: "Contribute to Fabric itself: file feature requests and bug reports as GitHub issues on the Fabric repo."
version: 1.0.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [GitHub, Fabric, Contributing, Issues, Feature-Request, Bug-Report]
    related_skills: [github-auth, github-issues]
---

# Contribute to Fabric

Use this skill when the user wants to **request a feature**, **report a bug**, or
otherwise **contribute feedback to Fabric itself** — e.g.:

- "I wish Fabric could do X" / "file a feature request for Fabric"
- "Fabric crashed when I did Y" / "report this bug to the Fabric repo"
- "How do I contribute to Fabric?"

It files a well-formed issue on the upstream Fabric repository:

- **Repo:** `ObliviousOdin/fabric`
- **Issues:** https://github.com/ObliviousOdin/fabric/issues

## Prerequisites

The user must be signed in to GitHub. `fabric setup github` handles this (device
code sign-in, saved as `GITHUB_TOKEN` in `~/.fabric/.env`). Detect credentials
with the shared helper:

```bash
source skills/github/github-auth/scripts/gh-env.sh
# Sets GH_AUTH_METHOD (gh | curl | none) and GITHUB_TOKEN / GH_USER
```

If `GH_AUTH_METHOD` is `none`, tell the user to run `fabric setup github` (or see
the `github-auth` skill) and stop — do not try to file an issue unauthenticated.

## Workflow

### 1. Gather the details

Before touching the API, make sure you can fill in a complete issue:

- **Feature request** — what they want, why (motivation), how it might work.
  Use `templates/feature-request.md` as the body skeleton.
- **Bug report** — what happened, steps to reproduce, expected vs. actual.
  Use `templates/bug-report.md` as the body skeleton. Enrich the Environment
  section yourself where possible:

```bash
fabric --version 2>/dev/null || python3 -c "import importlib.metadata as m; print(m.version('fabric'))" 2>/dev/null
uname -sr
python3 --version
```

Never include secrets (API keys, tokens, `.env` contents) in an issue body,
even inside error output the user pastes — redact them.

### 2. Check for duplicates

Search existing issues first and show the user anything similar:

```bash
QUERY="the user's summary in a few keywords"

# With gh
gh search issues --repo ObliviousOdin/fabric --state all --limit 10 "$QUERY"

# With curl
curl -s -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/search/issues?q=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$QUERY repo:ObliviousOdin/fabric")" \
  | python3 -c "
import sys, json
for i in json.load(sys.stdin).get('items', []):
    print(f\"#{i['number']}  {i['state']:6}  {i['title']}\n   {i['html_url']}\")"
```

If a matching open issue exists, offer to add a 👍 reaction or a comment with
the user's details instead of filing a duplicate.

### 3. Confirm, then file the issue

Show the user the final title and body and get their OK before posting —
this is published publicly under their GitHub account. Then:

```bash
# With the bundled helper (works with gh or curl auth)
skills/github/fabric-contribute/scripts/fabric-issue.sh \
  "Concise, specific title" \
  /path/to/body.md \
  "enhancement"          # label: enhancement | bug (best-effort, optional)

# Or directly with gh
gh issue create --repo ObliviousOdin/fabric \
  --title "Concise, specific title" \
  --body-file /path/to/body.md \
  --label enhancement
```

If labeling fails (labels need triage permission on some repos), file the
issue without labels rather than failing — maintainers will triage it.

### 4. Report back

Give the user the issue URL from the response, e.g.:

> Filed: https://github.com/ObliviousOdin/fabric/issues/123

## Title Guidelines

- Specific and searchable: "TTS setup crashes when no audio device is present",
  not "bug in setup"
- Feature requests state the capability: "Support Ollama model auto-pull during setup"
- No trailing punctuation, under ~80 characters

## Other Ways to Contribute

If the user wants to contribute *code* rather than an issue:

- Point them at `CONTRIBUTING.md` in the repo root
- Fork + branch + PR workflow is covered by the `github-pr-workflow` skill
- Starring the repo (offered during `fabric setup github`) also helps:
  `gh api -X PUT /user/starred/ObliviousOdin/fabric` or
  `curl -X PUT -H "Authorization: token $GITHUB_TOKEN" -H "Content-Length: 0" https://api.github.com/user/starred/ObliviousOdin/fabric`
