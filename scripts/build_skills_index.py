#!/usr/bin/env python3
"""Build the Fabric Skills Index — a centralized JSON catalog of all skills.

This script crawls every skill source (skills.sh, GitHub taps, official,
clawhub, lobehub, claude-marketplace) and writes a JSON index with resolved
GitHub paths. The index is served as a static file on the docs site so that
`fabric skills search/install` can use it without hitting the GitHub API.

Usage:
    # Local (uses gh CLI or GITHUB_TOKEN for auth)
    python scripts/build_skills_index.py

    # CI (set GITHUB_TOKEN as secret)
    GITHUB_TOKEN=ghp_... python scripts/build_skills_index.py

Output: website/static/api/skills-index.json
"""

import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

# Allow importing from repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Ensure the canonical home is set for tools/skills_hub.py imports.
os.environ.setdefault("FABRIC_HOME", os.path.join(os.path.expanduser("~"), ".fabric"))

from tools.skills_hub import (
    GitHubAuth,
    GitHubSource,
    SkillsShSource,
    OptionalSkillSource,
    WellKnownSkillSource,
    ClawHubSource,
    ClaudeMarketplaceSource,
    LobeHubSource,
    BrowseShSource,
    SkillMeta,
)
import httpx

OUTPUT_PATH = os.path.join(REPO_ROOT, "website", "static", "api", "skills-index.json")
INDEX_VERSION = 1

# Curated GitHub skill-pack taps crawled at index-build time only. Sourced
# from the Skills Ecosystem Directory research seed
# (website/static/api/skills-sources.json, rendered at
# website/docs/reference/skills-ecosystem-directory.md); every entry's path
# was verified against the repo's live tree before inclusion. These stay out
# of GitHubSource.DEFAULT_TAPS deliberately: runtime CLI searches enumerate
# every tap on a cold cache, while this build-time crawl uses two GitHub API
# calls per repo (branch + tree) and unauthenticated raw.githubusercontent
# fetches for SKILL.md metadata, so the catalog can be large without
# exhausting CI rate limits. Trust level remains "community" unless the repo
# is in tools/skills_guard.py TRUSTED_REPOS — installs always pass the
# skills guard scan and quarantine.
CURATED_TAPS = [
    # ── Atlas additions (2026-07 agent-skills atlas research pass) ──
    {"repo": "aaron-he-zhu/aaron-marketing-skills", "path": "protocol/"},  # A2, ~8 skills
    {"repo": "aaron-he-zhu/aaron-marketing-skills", "path": "ad/activate/"},  # A2, ~4 skills
    {"repo": "aaron-he-zhu/aaron-marketing-skills", "path": "ad/orchestrate/"},  # A2, ~4 skills
    {"repo": "addyosmani/agent-skills", "path": "skills/"},  # A2, ~24 skills
    {"repo": "aedev-tools/kling-3-prompting-skill", "path": "skills/"},  # C, ~1 skills
    {"repo": "Agents365-ai/excalidraw-skill", "path": "skills/"},  # C, ~1 skills
    {"repo": "Agents365-ai/mermaid-skill", "path": "skills/"},  # C, ~1 skills
    {"repo": "Agents365-ai/plantuml-skill", "path": "skills/"},  # C, ~1 skills
    {"repo": "Agile-V/agile_v_skills", "path": ""},  # C, ~32 skills
    {"repo": "Agile-V/agile_v_skills", "path": "skills/"},  # C, ~6 skills
    {"repo": "Agile-V/agile_v_skills", "path": "domains/"},  # C, ~5 skills
    {"repo": "AgriciDaniel/claude-seo", "path": "skills/"},  # A2, ~25 skills
    {"repo": "AgriciDaniel/claude-seo", "path": "extensions/ahrefs/skills/"},  # A2, ~1 skills
    {"repo": "AgriciDaniel/claude-seo", "path": "extensions/banana/skills/"},  # A2, ~1 skills
    {"repo": "akin-ozer/cc-devops-skills", "path": "devops-skills-plugin/skills/"},  # A2, ~31 skills
    {"repo": "akseolabs-seo/cinematic-ui", "path": ""},  # C, ~1 skills
    {"repo": "akshaykokane/Building-Customer-Service-Agent-with-Skill.md-and-Agent-Framework", "path": "Agents/Assets/Skills/"},  # C, ~1 skills
    {"repo": "allenai/asta-plugins", "path": "plugins/asta-tools/skills/"},  # A1, ~14 skills
    {"repo": "allenai/asta-plugins", "path": "plugins/asta-assistant/skills/"},  # A1, ~7 skills
    {"repo": "allenai/asta-plugins", "path": "plugins/asta-dev/skills/"},  # A1, ~2 skills
    {"repo": "anthropics/knowledge-work-plugins", "path": "small-business/skills/"},  # A1, ~31 skills
    {"repo": "anthropics/knowledge-work-plugins", "path": "partner-built/zoom-plugin/skills/"},  # A1, ~30 skills
    {"repo": "anthropics/knowledge-work-plugins", "path": "data/skills/"},  # A1, ~10 skills
    {"repo": "antonbabenko/terraform-skill", "path": "skills/"},  # A2, ~1 skills
    {"repo": "antvis/chart-visualization-skills", "path": "skills/"},  # A1, ~8 skills
    {"repo": "atc-net/atc-agentic-toolkit", "path": "plugins/azure/skills/"},  # C, ~198 skills
    {"repo": "atc-net/atc-agentic-toolkit", "path": "plugins/common/skills/"},  # C, ~14 skills
    {"repo": "atc-net/atc-agentic-toolkit", "path": "plugins/cosmosdb/skills/"},  # C, ~14 skills
    {"repo": "aws/agent-toolkit-for-aws", "path": "plugins/aws-core/skills/"},  # A1, ~19 skills
    {"repo": "aws/agent-toolkit-for-aws", "path": "skills/core-skills/"},  # A1, ~19 skills
    {"repo": "aws/agent-toolkit-for-aws", "path": "skills/specialized-skills/database-skills/"},  # A1, ~14 skills
    {"repo": "CodeAlive-AI/ceo-ai-os", "path": "skills/"},  # C, ~79 skills
    {"repo": "content-designer/ux-writing-skill", "path": ""},  # C, ~1 skills
    {"repo": "cookiy-ai/user-research-skill", "path": ""},  # B, ~1 skills
    {"repo": "cookiy-ai/user-research-skill", "path": "plugins/user-research/skills/"},  # B, ~1 skills
    {"repo": "cypress-io/ai-toolkit", "path": "skills/"},  # A1, ~3 skills
    {"repo": "dadederk/iOS-Accessibility-Agent-Skill", "path": ""},  # A2, ~1 skills
    {"repo": "data-goblin/power-bi-agentic-development", "path": "plugins/semantic-models/skills/"},  # A2, ~6 skills
    {"repo": "data-goblin/power-bi-agentic-development", "path": "plugins/custom-visuals/skills/"},  # A2, ~5 skills
    {"repo": "data-goblin/power-bi-agentic-development", "path": "plugins/reports/skills/"},  # A2, ~5 skills
    {"repo": "databricks/databricks-agent-skills", "path": "plugins/databricks/claude/skills/"},  # A1, ~29 skills
    {"repo": "databricks/databricks-agent-skills", "path": "plugins/databricks/copilot/skills/"},  # A1, ~29 skills
    {"repo": "deanpeters/Product-Manager-Skills", "path": "skills/"},  # A2, ~70 skills
    {"repo": "digitalsamba/claude-code-video-toolkit", "path": ".claude/skills/"},  # B, ~12 skills
    {"repo": "digitalsamba/claude-code-video-toolkit", "path": "skills/"},  # B, ~1 skills
    {"repo": "dotnet/skills", "path": "plugins/dotnet-test/skills/"},  # A1, ~20 skills
    {"repo": "dotnet/skills", "path": "plugins/dotnet-msbuild/skills/"},  # A1, ~19 skills
    {"repo": "dotnet/skills", "path": "plugins/dotnet-blazor/skills/"},  # A1, ~9 skills
    {"repo": "fayazara/macos-app-skills", "path": ""},  # A2, ~6 skills
    {"repo": "FireRedTeam/FireRed-OpenStoryline", "path": ".storyline/skills/"},  # B, ~5 skills
    {"repo": "FireRedTeam/FireRed-OpenStoryline", "path": ".claude/skills/"},  # B, ~2 skills
    {"repo": "flutter/agent-plugins", "path": "skills/"},  # A1, ~22 skills
    {"repo": "flutter/agent-plugins", "path": ".agents/agents/reidbaker-agent/skills/"},  # A1, ~6 skills
    {"repo": "fluxcd/agent-skills", "path": "internal/skills/"},  # A1, ~3 skills
    {"repo": "fluxcd/agent-skills", "path": "skills/"},  # A1, ~3 skills
    {"repo": "getdex/agent-skills", "path": ""},  # A1, ~1 skills
    {"repo": "GitGuardian/agent-skills", "path": "skills/"},  # A1, ~6 skills
    {"repo": "gtmagents/gtm-agents", "path": "plugins/content-marketing/skills/"},  # B, ~7 skills
    {"repo": "gtmagents/gtm-agents", "path": "plugins/community-building/skills/"},  # B, ~6 skills
    {"repo": "gtmagents/gtm-agents", "path": "plugins/design-creative/skills/"},  # B, ~6 skills
    {"repo": "Hack23/homepage", "path": ".github/skills/security/"},  # C, ~18 skills
    {"repo": "Hack23/homepage", "path": ".github/skills/governance/"},  # C, ~7 skills
    {"repo": "Hack23/homepage", "path": ".github/skills/integration/"},  # C, ~7 skills
    {"repo": "hiteshK03/video-production-skill", "path": ""},  # C, ~1 skills
    {"repo": "igorrendulic/tg-customer-support-plugin", "path": "skills/"},  # C, ~1 skills
    {"repo": "itsmostafa/aws-agent-skills", "path": "skills/"},  # B, ~18 skills
    {"repo": "jeffallan/claude-skills", "path": "skills/"},  # A2, ~66 skills
    {"repo": "julianoczkowski/designer-skills", "path": ""},  # A2, ~8 skills
    {"repo": "jwynia/agent-skills", "path": "skills/creative/fiction/application/"},  # A2, ~14 skills
    {"repo": "jwynia/agent-skills", "path": "skills/creative/fiction/structure/"},  # A2, ~12 skills
    {"repo": "jwynia/agent-skills", "path": "skills/creative/fiction/worldbuilding/"},  # A2, ~11 skills
    {"repo": "kkunkunya/ppt-maker-agent-plugin", "path": "plugins/ppt-maker/skills/"},  # C, ~6 skills
    {"repo": "konraddzbik/architecture-diagram-skill", "path": "skills/"},  # C, ~1 skills
    {"repo": "krayin/agent-skills", "path": "skills/"},  # A1, ~2 skills
    {"repo": "lackeyjb/playwright-skill", "path": "skills/"},  # B, ~1 skills
    {"repo": "LambdaTest/agent-skills", "path": ""},  # A1, ~47 skills
    {"repo": "LambdaTest/agent-skills", "path": "api-skill/"},  # A1, ~17 skills
    {"repo": "LambdaTest/agent-skills", "path": "api-skill/postman/"},  # A1, ~4 skills
    {"repo": "lottiefiles/motion-design-skill", "path": "skills/"},  # A1, ~1 skills
    {"repo": "LukasNiessen/kubernetes-skill", "path": ""},  # B, ~1 skills
    {"repo": "LuoJiangYong/muse-video-skill", "path": ""},  # C, ~1 skills
    {"repo": "lycfyi/community-agent-plugin", "path": "plugins/discord-user-connector/skills/"},  # C, ~8 skills
    {"repo": "lycfyi/community-agent-plugin", "path": "plugins/telegram-connector/skills/"},  # C, ~6 skills
    {"repo": "lycfyi/community-agent-plugin", "path": "plugins/community-agent/skills/"},  # C, ~5 skills
    {"repo": "mblode/agent-skills", "path": "skills/"},  # A2, ~26 skills
    {"repo": "mgifford/accessibility-skills", "path": "skills/"},  # A2, ~27 skills
    {"repo": "mgifford/accessibility-skills", "path": "ai-workflows/"},  # A2, ~2 skills
    {"repo": "microsoft/skills-for-fabric", "path": "skills/"},  # A1, ~35 skills
    {"repo": "microsoft/skills-for-fabric", "path": "plugins/fabric-skills/skills/"},  # A1, ~31 skills
    {"repo": "microsoft/skills-for-fabric", "path": "plugins/fabric-authoring/skills/"},  # A1, ~12 skills
    {"repo": "microsoft/win-dev-skills", "path": "plugins/winui/skills/"},  # B, ~8 skills
    {"repo": "mikemai2awesome/agent-skills", "path": "skills/"},  # C, ~9 skills
    {"repo": "minhnv0807/ai-business-skills", "path": "skills/vi/"},  # B, ~25 skills
    {"repo": "minhnv0807/ai-business-skills", "path": "skills/en/"},  # B, ~24 skills
    {"repo": "minhnv0807/ai-business-skills", "path": "modules/personal-branding/en/"},  # B, ~7 skills
    {"repo": "MLOps-Courses/mlops-coding-skills", "path": ""},  # C, ~7 skills
    {"repo": "murphye/agent-skills-customer-service", "path": "skills/"},  # C, ~1 skills
    {"repo": "NeoLabHQ/context-engineering-kit", "path": "plugins/customaize-agent/skills/"},  # A2, ~13 skills
    {"repo": "NeoLabHQ/context-engineering-kit", "path": "plugins/sadd/skills/"},  # A2, ~10 skills
    {"repo": "NeoLabHQ/context-engineering-kit", "path": "plugins/git/skills/"},  # A2, ~9 skills
    {"repo": "new-silvermoon/awesome-android-agent-skills", "path": ".github/skills/ui/"},  # B, ~4 skills
    {"repo": "new-silvermoon/awesome-android-agent-skills", "path": ".github/skills/architecture/"},  # B, ~3 skills
    {"repo": "new-silvermoon/awesome-android-agent-skills", "path": ".github/skills/concurrency_and_networking/"},  # B, ~3 skills
    {"repo": "oakoss/agent-skills", "path": "skills/"},  # C, ~132 skills
    {"repo": "omkamal/pypict-claude-skill", "path": ""},  # C, ~1 skills
    {"repo": "oncesylvia/fundraising-skills", "path": "skills/"},  # C, ~10 skills
    {"repo": "pixeltable/pixeltable-skill", "path": "skills/"},  # C, ~1 skills
    {"repo": "preset-io/agent-skills", "path": "plugins/preset-api-skills/skills/"},  # A1, ~17 skills
    {"repo": "preset-io/agent-skills", "path": "plugins/preset-mcp-skills/skills/"},  # A1, ~9 skills
    {"repo": "preset-io/agent-skills", "path": "plugins/preset-cli-skills/skills/"},  # A1, ~2 skills
    {"repo": "product-on-purpose/pm-skills", "path": "skills/"},  # A2, ~68 skills
    {"repo": "psenger/ai-agent-skills", "path": "skills/"},  # C, ~11 skills
    {"repo": "psenger/ai-agent-skills", "path": ".claude/skills/"},  # C, ~3 skills
    {"repo": "rampstackco/claude-skills", "path": "skills/"},  # B, ~103 skills
    {"repo": "realkimbarrett/advertising-skills", "path": "skills/copy-chief/"},  # B, ~4 skills
    {"repo": "realkimbarrett/advertising-skills", "path": "skills/operator-os/"},  # B, ~4 skills
    {"repo": "realkimbarrett/advertising-skills", "path": "skills/foundations/"},  # B, ~2 skills
    {"repo": "rowanbrooks100/brand-strategy-skill", "path": ""},  # C, ~1 skills
    {"repo": "ruvnet/claude-flow", "path": ".claude/skills/"},  # B, ~38 skills
    {"repo": "ScaleBrick/founder-marketing-skills", "path": "skills/"},  # C, ~4 skills
    {"repo": "softaworks/agent-toolkit", "path": "skills/"},  # A2, ~43 skills
    {"repo": "spencerpauly/awesome-cursor-skills", "path": "resources/"},  # B, ~65 skills
    {"repo": "testdino-hq/playwright-skill", "path": ""},  # B, ~6 skills
    {"repo": "TheCraigHewitt/skills", "path": "sales/"},  # A2, ~21 skills
    {"repo": "TheCraigHewitt/skills", "path": "cowork/"},  # A2, ~16 skills
    {"repo": "TheCraigHewitt/skills", "path": "youtube/"},  # A2, ~15 skills
    {"repo": "timescale/pg-aiguide", "path": "skills/"},  # B, ~10 skills
    {"repo": "tjboudreaux/cc-skills-vc-fundraising", "path": "skills/"},  # C, ~2 skills
    {"repo": "tuanductran/hr-skills", "path": "skills/"},  # C, ~146 skills
    {"repo": "tuanductran/hr-skills", "path": ""},  # C, ~1 skills
    {"repo": "wondelai/skills", "path": ""},  # B, ~62 skills
    {"repo": "wulaosiji/founder-skills", "path": "skills/"},  # C, ~24 skills
    {"repo": "yetone/native-feel-skill", "path": ""},  # B, ~1 skills    {"repo": "alirezarezvani/claude-skills", "path": "c-level-advisor/skills/"},  # B, ~34 skills
    {"repo": "alirezarezvani/claude-skills", "path": "engineering/skills/"},  # B, ~38 skills
    {"repo": "alirezarezvani/claude-skills", "path": "marketing-skill/skills/"},  # B, ~47 skills
    {"repo": "AbdullahHameedKhan/karpathy-ponytail-skills", "path": "skills/"},  # C, ~1 skill
    {"repo": "Aperivue/medsci-skills", "path": "skills/"},  # B, ~56 skills
    {"repo": "apify/agent-skills", "path": "skills/"},  # A1, ~5 skills
    {"repo": "apollographql/skills", "path": "skills/"},  # A1, ~14 skills
    {"repo": "arvindrk/extract-design-system", "path": "skills/"},  # A2, ~1 skills
    {"repo": "astronomer/agents", "path": "astro-airflow-mcp/.claude/skills/"},  # A1, ~1 skills
    {"repo": "astronomer/agents", "path": "skills/"},  # A1, ~34 skills
    {"repo": "auth0/agent-skills", "path": "plugins/auth0/skills/"},  # A1, ~1 skills
    {"repo": "automattic/agent-skills", "path": "skills/"},  # A1, ~13 skills
    {"repo": "axiomhq/skills", "path": "skills/"},  # A1, ~8 skills
    {"repo": "base/skills", "path": ".claude/skills/"},  # A1, ~2 skills
    {"repo": "base/skills", "path": "skills/"},  # A1, ~2 skills
    {"repo": "better-auth/skills", "path": "better-auth/"},  # A1, ~5 skills
    {"repo": "bevibing/tutor-skills", "path": "skills/"},  # A2, ~2 skills
    {"repo": "bitwarden/ai-plugins", "path": "plugins/bitwarden-code-review/skills/"},  # A1, ~7 skills
    {"repo": "bitwarden/ai-plugins", "path": "plugins/bitwarden-delivery-tools/skills/"},  # A1, ~10 skills
    {"repo": "bitwarden/ai-plugins", "path": "plugins/bitwarden-security-engineer/skills/"},  # A1, ~9 skills
    {"repo": "bitwarden/ai-plugins", "path": "plugins/bitwarden-shepherd/skills/"},  # A1, ~7 skills
    {"repo": "box/box-for-ai", "path": "skills/"},  # A1, ~5 skills
    {"repo": "brave/brave-search-skills", "path": "clawhub/"},  # A1, ~1 skills
    {"repo": "brave/brave-search-skills", "path": "skills/"},  # A1, ~11 skills
    {"repo": "BrianRWagner/ai-marketing-claude-code-skills", "path": ""},  # B, ~23 skills
    {"repo": "browser-use/browser-use", "path": "browser_use/skills/"},  # A1, ~1 skills
    {"repo": "browser-use/browser-use", "path": "skills/"},  # A1, ~6 skills
    {"repo": "browserbase/skills", "path": "skills/"},  # A1, ~16 skills
    {"repo": "callstackincubator/agent-skills", "path": ".claude/skills/"},  # A1, ~1 skills
    {"repo": "callstackincubator/agent-skills", "path": "skills/"},  # A1, ~9 skills
    {"repo": "clerk/skills", "path": "skills/core/"},  # A1, ~5 skills
    {"repo": "clerk/skills", "path": "skills/features/"},  # A1, ~4 skills
    {"repo": "clerk/skills", "path": "skills/frameworks/"},  # A1, ~8 skills
    {"repo": "clerk/skills", "path": "skills/mobile/"},  # A1, ~3 skills
    {"repo": "clickhouse/agent-skills", "path": "skills/"},  # A1, ~11 skills
    {"repo": "cloudflare/skills", "path": "skills/"},  # A1, ~11 skills
    {"repo": "coderabbitai/skills", "path": "skills/"},  # A1, ~2 skills
    {"repo": "contentful/skills", "path": "skills/"},  # A1, ~5 skills
    {"repo": "contentful/skills", "path": "skills/contentful-apps/"},  # A1, ~2 skills
    {"repo": "contentstack/contentstack-agent-skills", "path": "skills/"},  # A1, ~21 skills
    {"repo": "convex-dev/convex", "path": "skills/"},  # A1, ~9 skills
    {"repo": "dagster-io/skills", "path": "skills/dagster-expert/skills/"},  # A1, ~1 skills
    {"repo": "dagster-io/skills", "path": "skills/dignified-python/skills/"},  # A1, ~1 skills
    {"repo": "dash0hq/agent-skills", "path": "skills/"},  # A1, ~4 skills
    {"repo": "datadog-labs/agent-skills", "path": ""},  # A1, ~8 skills
    {"repo": "datadog-labs/agent-skills", "path": "agent-observability/"},  # A1, ~6 skills
    {"repo": "datadog-labs/agent-skills", "path": "dd-apm/k8s-ssi/"},  # A1, ~5 skills
    {"repo": "datadog-labs/agent-skills", "path": "dd-apm/linux-ssi/"},  # A1, ~5 skills
    {"repo": "dbt-labs/dbt-agent-skills", "path": ".claude/skills/"},  # A1, ~1 skills
    {"repo": "dbt-labs/dbt-agent-skills", "path": "skills/dbt-extras/skills/"},  # A1, ~1 skills
    {"repo": "dbt-labs/dbt-agent-skills", "path": "skills/dbt-migration/skills/"},  # A1, ~2 skills
    {"repo": "dbt-labs/dbt-agent-skills", "path": "skills/dbt/skills/"},  # A1, ~10 skills
    {"repo": "deepgram/skills", "path": "skills/"},  # A1, ~6 skills
    {"repo": "denoland/skills", "path": "skills/"},  # A1, ~6 skills
    {"repo": "DietrichGebert/ponytail", "path": "skills/"},  # A2, ~6 skills
    {"repo": "elevenlabs/skills", "path": ""},  # A1, ~9 skills
    {"repo": "emilkowalski/skills", "path": "skills/"},  # A2, ~6 skills
    {"repo": "encoredev/skills", "path": "encore/"},  # A1, ~28 skills
    {"repo": "exploreomni/omni-agent-skills", "path": "skills/"},  # A1, ~9 skills
    {"repo": "exploreomni/omni-agent-skills", "path": "skills/omni-integrations/skills/"},  # A1, ~2 skills
    {"repo": "expo/skills", "path": ".claude/skills/"},  # A1, ~1 skills
    {"repo": "expo/skills", "path": "plugins/expo/skills/"},  # A1, ~21 skills
    {"repo": "facebook/react", "path": ".claude/skills/"},  # A1, ~7 skills
    {"repo": "factory-ai/factory-plugins", "path": "plugins/core/skills/"},  # A1, ~4 skills
    {"repo": "factory-ai/factory-plugins", "path": "plugins/droid-control/skills/"},  # A1, ~11 skills
    {"repo": "factory-ai/factory-plugins", "path": "plugins/droid-evolved/skills/"},  # A1, ~6 skills
    {"repo": "factory-ai/factory-plugins", "path": "plugins/security-engineer/skills/"},  # A1, ~4 skills
    {"repo": "figma/mcp-server-guide", "path": "skills/"},  # A1, ~12 skills
    {"repo": "figma/mcp-server-guide", "path": "workflow-skills/"},  # A1, ~2 skills
    {"repo": "firebase/agent-skills", "path": "skills/"},  # A1, ~11 skills
    {"repo": "firecrawl/cli", "path": "skills/"},  # A1, ~10 skills
    {"repo": "flutter/skills", "path": "skills/"},  # A1, ~22 skills
    {"repo": "garrytan/gstack", "path": "browser-skills/"},  # A2, ~1 skills
    {"repo": "getsentry/skills", "path": "skills/"},  # A1, ~28 skills
    {"repo": "github/awesome-copilot", "path": "skills/"},  # A1, ~376 skills
    {"repo": "google-gemini/gemini-skills", "path": "skills/"},  # A1, ~4 skills
    {"repo": "google-labs-code/stitch-skills", "path": "plugins/stitch-build/skills/"},  # A1, ~5 skills
    {"repo": "google-labs-code/stitch-skills", "path": "plugins/stitch-design/skills/"},  # A1, ~6 skills
    {"repo": "google-labs-code/stitch-skills", "path": "plugins/stitch-utilities/skills/"},  # A1, ~4 skills
    {"repo": "harvard-lil/lawskills-hub", "path": "skills/cle/"},  # A2, ~4 skills
    {"repo": "harvard-lil/lawskills-hub", "path": "skills/professor/"},  # A2, ~4 skills
    {"repo": "harvard-lil/lawskills-hub", "path": "skills/skill-developer/"},  # A2, ~4 skills
    {"repo": "harvard-lil/lawskills-hub", "path": "skills/student/"},  # A2, ~4 skills
    {"repo": "hashicorp/agent-skills", "path": "packer/builders/skills/"},  # A1, ~3 skills
    {"repo": "hashicorp/agent-skills", "path": "terraform/code-generation/skills/"},  # A1, ~4 skills
    {"repo": "hashicorp/agent-skills", "path": "terraform/module-generation/skills/"},  # A1, ~2 skills
    {"repo": "hashicorp/agent-skills", "path": "terraform/provider-development/skills/"},  # A1, ~6 skills
    {"repo": "heygen-com/hyperframes", "path": "skills/"},  # A2, ~19 skills
    {"repo": "higgsfield-ai/skills", "path": ""},  # A2, ~7 skills
    {"repo": "huggingface/skills", "path": "hf-mcp/skills/"},  # A1, ~1 skills
    {"repo": "K-Dense-AI/claude-scientific-writer", "path": "skills/"},  # A2, ~24 skills
    {"repo": "K-Dense-AI/scientific-agent-skills", "path": "skills/"},  # A2, ~149 skills
    {"repo": "kotlin/kotlin-agent-skills", "path": "skills/"},  # A1, ~6 skills
    {"repo": "KuangshiAi/SciVisAgentSkills", "path": ""},  # B, ~4 skills
    {"repo": "langchain-ai/langchain-skills", "path": "config/skills/"},  # A1, ~14 skills
    {"repo": "langfuse/skills", "path": "skills/"},  # A1, ~1 skills
    {"repo": "launchdarkly/agent-skills", "path": "skills/agentcontrol/"},  # A1, ~24 skills
    {"repo": "launchdarkly/agent-skills", "path": "skills/feature-flags/"},  # A1, ~6 skills
    {"repo": "launchdarkly/agent-skills", "path": "skills/metrics/"},  # A1, ~3 skills
    {"repo": "launchdarkly/agent-skills", "path": "skills/observability/"},  # A1, ~4 skills
    {"repo": "lawve-ai/awesome-legal-skills", "path": "skills/"},  # B, ~139 skills
    {"repo": "LeadMagic/gtm-skills", "path": "skills/analytics/"},  # B, ~13 skills
    {"repo": "LeadMagic/gtm-skills", "path": "skills/automation/"},  # B, ~12 skills
    {"repo": "LeadMagic/gtm-skills", "path": "skills/founder-led/"},  # B, ~41 skills
    {"repo": "LeadMagic/gtm-skills", "path": "skills/tools/"},  # B, ~15 skills
    {"repo": "LegalQuants/lq-skills", "path": "skills/"},  # B, ~47 skills
    {"repo": "LegalQuants/lq-skills", "path": "skills/coquill/"},  # B, ~3 skills
    {"repo": "livekit/agent-skills", "path": "skills/"},  # A1, ~2 skills
    {"repo": "makenotion/skills", "path": "skills/"},  # A1, ~1 skills
    {"repo": "mapbox/mapbox-agent-skills", "path": "skills/"},  # A1, ~19 skills
    {"repo": "mastra-ai/skills", "path": "skills/"},  # A1, ~1 skills
    {"repo": "mattpocock/skills", "path": "skills/engineering/"},  # A2, ~17 skills
    {"repo": "mattpocock/skills", "path": "skills/productivity/"},  # A2, ~5 skills
    {"repo": "mcp-use/mcp-use", "path": "skills/"},  # A1, ~4 skills
    {"repo": "medusajs/medusa-agent-skills", "path": "plugins/ecommerce-storefront/skills/"},  # A1, ~1 skills
    {"repo": "medusajs/medusa-agent-skills", "path": "plugins/learn-medusa/skills/"},  # A1, ~1 skills
    {"repo": "medusajs/medusa-agent-skills", "path": "plugins/medusa-cloud/skills/"},  # A1, ~9 skills
    {"repo": "medusajs/medusa-agent-skills", "path": "plugins/medusa-dev/skills/"},  # A1, ~7 skills
    {"repo": "microsoft/azure-skills", "path": "skills/"},  # A1, ~27 skills
    {"repo": "microsoft/azure-skills", "path": "skills/microsoft-foundry/models/deploy-model/"},  # A1, ~3 skills
    {"repo": "n8n-io/n8n", "path": "packages/@n8n/instance-ai/skills/"},  # A1, ~10 skills
    {"repo": "neondatabase/agent-skills", "path": "skills/"},  # A1, ~8 skills
    {"repo": "nextlevelbuilder/ui-ux-pro-max-skill", "path": ".claude/skills/"},  # B, ~7 skills
    {"repo": "nextlevelbuilder/ui-ux-pro-max-skill", "path": "cli/assets/skills/"},  # B, ~6 skills
    {"repo": "nuxt/ui", "path": "skills/"},  # A1, ~1 skills
    {"repo": "nvidia/skills", "path": "plugins/nvidia-skills/skills/"},  # A1, ~12 skills
    {"repo": "OpenBB-finance/OpenBB", "path": "openbb_platform/extensions/mcp_server/openbb_mcp_server/skills/"},  # A2, ~4 skills
    {"repo": "openclaw/openclaw", "path": "extensions/feishu/skills/"},  # B, ~4 skills
    {"repo": "openclaw/openclaw", "path": "extensions/qqbot/skills/"},  # B, ~3 skills
    {"repo": "openclaw/openclaw", "path": "skills/"},  # B, ~51 skills
    {"repo": "openshift/hypershift", "path": ".claude/skills/"},  # A1, ~8 skills
    {"repo": "openshift/hypershift", "path": ".claude/skills/dev/"},  # A1, ~7 skills
    {"repo": "parallel-web/parallel-agent-skills", "path": "skills/"},  # A1, ~10 skills
    {"repo": "phuryn/pm-skills", "path": "pm-market-research/skills/"},  # A2, ~7 skills
    {"repo": "phuryn/pm-skills", "path": "pm-product-strategy/skills/"},  # A2, ~12 skills
    {"repo": "pinecone-io/skills", "path": "skills/"},  # A1, ~9 skills
    {"repo": "planetscale/database-skills", "path": "skills/"},  # A1, ~4 skills
    {"repo": "posthog/skills", "path": "skills/posthog/all/skills/"},  # A1, ~79 skills
    {"repo": "posthog/skills", "path": "skills/posthog/feature-flags/skills/"},  # A1, ~18 skills
    {"repo": "posthog/skills", "path": "skills/posthog/integration/skills/"},  # A1, ~33 skills
    {"repo": "prisma/skills", "path": ""},  # A1, ~9 skills
    {"repo": "projectopensea/opensea-skill", "path": ""},  # A1, ~6 skills
    {"repo": "pulumi/agent-skills", "path": "delegation/skills/"},  # A1, ~1 skills
    {"repo": "pulumi/agent-skills", "path": "migration/skills/"},  # A1, ~4 skills
    {"repo": "pulumi/agent-skills", "path": "package-maintenance/skills/"},  # A1, ~2 skills
    {"repo": "pulumi/agent-skills", "path": "pulumi/skills/"},  # A1, ~8 skills
    {"repo": "pytorch/pytorch", "path": ".claude/skills/"},  # A1, ~16 skills
    {"repo": "redis/agent-skills", "path": "skills/"},  # A1, ~8 skills
    {"repo": "remotion-dev/skills", "path": "skills/"},  # A1, ~9 skills
    {"repo": "remotion-dev/skills", "path": "skills/remotion-best-practices/"},  # A1, ~8 skills
    {"repo": "resend/resend-skills", "path": "skills/"},  # A1, ~5 skills
    {"repo": "rivet-dev/skills", "path": ""},  # A1, ~15 skills
    {"repo": "rivet-dev/skills", "path": "skills/"},  # A1, ~1 skills
    {"repo": "runwayml/skills", "path": "skills/"},  # A1, ~17 skills
    {"repo": "sanity-io/agent-toolkit", "path": "skills/"},  # A1, ~7 skills
    {"repo": "semgrep/skills", "path": "skills/"},  # A1, ~3 skills
    {"repo": "shopify/shopify-ai-toolkit", "path": "skills/"},  # A1, ~20 skills
    {"repo": "signoz/agent-skills", "path": "plugins/signoz/skills/"},  # A1, ~13 skills
    {"repo": "stripe/ai", "path": "providers/claude/plugin/skills/"},  # A1, ~5 skills
    {"repo": "supabase/agent-skills", "path": "skills/"},  # A1, ~2 skills
    {"repo": "sveltejs/ai-tools", "path": "plugins/claude/svelte/skills/"},  # A1, ~2 skills
    {"repo": "tavily-ai/skills", "path": "skills/"},  # A1, ~8 skills
    {"repo": "tinybirdco/tinybird-agent-skills", "path": "skills/"},  # A1, ~4 skills
    {"repo": "tldraw/tldraw", "path": "apps/mcp-app/.claude/skills/"},  # A1, ~4 skills
    {"repo": "tldraw/tldraw", "path": "skills/"},  # A1, ~22 skills
    {"repo": "triggerdotdev/skills", "path": ""},  # A1, ~6 skills
    {"repo": "upstash/context7", "path": "skills/"},  # A1, ~3 skills
    {"repo": "vercel-labs/agent-skills", "path": "skills/"},  # A1, ~9 skills
    {"repo": "vercel-labs/skills", "path": "skills/"},  # A1, ~1 skills
    {"repo": "vercel/ai", "path": "skills/"},  # A1, ~11 skills
    {"repo": "webflow/webflow-skills", "path": "plugins/webflow-skills/skills/"},  # A1, ~27 skills
    {"repo": "wix/skills", "path": "replatform/"},  # A1, ~9 skills
    {"repo": "wix/skills", "path": "skills/"},  # A1, ~7 skills
    {"repo": "wordpress/agent-skills", "path": "skills/"},  # A1, ~18 skills
    {"repo": "wshobson/agents", "path": "plugins/backend-development/skills/"},  # B, ~9 skills
    {"repo": "wshobson/agents", "path": "plugins/developer-essentials/skills/"},  # B, ~11 skills
    {"repo": "wshobson/agents", "path": "plugins/llm-finetuning/skills/"},  # B, ~10 skills
    {"repo": "wshobson/agents", "path": "plugins/python-development/skills/"},  # B, ~16 skills
]


def _meta_to_dict(meta: SkillMeta) -> dict:
    """Convert a SkillMeta to a serializable dict."""
    return {
        "name": meta.name,
        "description": meta.description,
        "source": meta.source,
        "identifier": meta.identifier,
        "trust_level": meta.trust_level,
        "repo": meta.repo or "",
        "path": meta.path or "",
        "tags": meta.tags or [],
        "extra": meta.extra or {},
    }


def crawl_source(source, source_name: str, limit: int) -> list:
    """Crawl a single source and return skill dicts."""
    print(f"  Crawling {source_name}...", flush=True)
    start = time.time()
    try:
        results = source.search("", limit=limit)
    except Exception as e:
        print(f"  Error crawling {source_name}: {e}", file=sys.stderr)
        return []
    skills = [_meta_to_dict(m) for m in results]
    elapsed = time.time() - start
    print(f"  {source_name}: {len(skills)} skills ({elapsed:.1f}s)", flush=True)
    return skills


def crawl_skills_sh(source: SkillsShSource) -> list:
    """Crawl skills.sh via its sitemap to enumerate the full catalog (~20k entries).

    Previously walked a hardcoded list of ~28 popular keywords (each capped at
    50 results) which yielded ~850 unique skills — about 4% of the real catalog.
    The SkillsShSource.search("") path now hits the sitemap directly, returning
    the full 20k-entry catalog deduplicated by canonical identifier.
    """
    print("  Crawling skills.sh (sitemap)...", flush=True)
    start = time.time()

    try:
        results = source.search("", limit=0)  # 0 = no cap, return the whole catalog
    except Exception as e:
        print(f"    Warning: skills.sh sitemap walk failed: {e}", file=sys.stderr)
        results = []

    all_skills: dict[str, dict] = {}
    for meta in results:
        entry = _meta_to_dict(meta)
        if entry["identifier"] not in all_skills:
            all_skills[entry["identifier"]] = entry

    elapsed = time.time() - start
    print(f"  skills.sh: {len(all_skills)} unique skills ({elapsed:.1f}s)",
          flush=True)
    return list(all_skills.values())


def _fetch_repo_branch_and_tree(repo: str, auth: GitHubAuth) -> tuple:
    """Fetch (default_branch, recursive tree entries) for a repo."""
    headers = auth.get_headers()
    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{repo}",
            headers=headers, timeout=15, follow_redirects=True,
        )
        if resp.status_code != 200:
            return "main", []
        branch = resp.json().get("default_branch", "main")

        resp = httpx.get(
            f"https://api.github.com/repos/{repo}/git/trees/{branch}",
            params={"recursive": "1"},
            headers=headers, timeout=30, follow_redirects=True,
        )
        if resp.status_code != 200:
            return branch, []
        data = resp.json()
        if data.get("truncated"):
            return branch, []
        return branch, data.get("tree", [])
    except Exception:
        return "main", []


def _fetch_repo_tree(repo: str, auth: GitHubAuth) -> list:
    """Fetch the recursive tree for a repo. Returns list of tree entries."""
    _branch, tree = _fetch_repo_branch_and_tree(repo, auth)
    return tree


def crawl_curated_taps(auth: GitHubAuth, github_source: GitHubSource) -> list:
    """Crawl CURATED_TAPS using tree lookups + raw.githubusercontent fetches.

    Cost model: two GitHub API calls per repo (branch + recursive tree),
    then one unauthenticated raw.githubusercontent request per SKILL.md —
    raw fetches don't count against the API rate limit, so a multi-thousand
    skill catalog stays within CI's GITHUB_TOKEN budget. Mirrors the
    runtime tap semantics: a skill is a direct child directory of the tap
    path containing a SKILL.md.
    """
    print(f"  Crawling {len(CURATED_TAPS)} curated taps...", flush=True)
    start = time.time()

    by_repo: dict[str, list] = defaultdict(list)
    for tap in CURATED_TAPS:
        by_repo[tap["repo"]].append(tap.get("path", ""))

    def _fetch_skill_md(repo: str, branch: str, skill_dir: str) -> dict | None:
        url = (
            f"https://raw.githubusercontent.com/{repo}/{branch}/"
            f"{skill_dir}/SKILL.md"
        )
        try:
            resp = httpx.get(url, timeout=15, follow_redirects=True)
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        try:
            fm = GitHubSource._parse_frontmatter_quick(resp.text)
        except Exception:
            fm = {}
        identifier = f"{repo}/{skill_dir}"
        name = str(fm.get("name") or skill_dir.split("/")[-1])
        description = str(fm.get("description") or "")
        raw_tags = fm.get("tags", [])
        tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []
        return {
            "name": name,
            "description": description,
            "source": "github",
            "identifier": identifier,
            "trust_level": github_source.trust_level_for(identifier),
            "repo": repo,
            "path": skill_dir,
            "tags": tags,
            "extra": {"curated": True},
        }

    def _crawl_repo(repo: str, tap_paths: list) -> list:
        branch, tree = _fetch_repo_branch_and_tree(repo, auth)
        if not tree:
            return []
        blob_paths = {
            item.get("path", "")
            for item in tree
            if item.get("type") == "blob"
        }
        skill_dirs: list[str] = []
        for tap_path in tap_paths:
            prefix = tap_path.rstrip("/")
            prefix = f"{prefix}/" if prefix else ""
            seen: set[str] = set()
            for path in blob_paths:
                if not path.startswith(prefix) or not path.endswith("/SKILL.md"):
                    continue
                rest = path[len(prefix):]
                parts = rest.split("/")
                # Direct child dir only — matches _list_skills_in_repo, and
                # skip dot/underscore dirs the runtime lister also skips.
                if len(parts) != 2 or parts[0].startswith((".", "_")):
                    continue
                skill_dir = f"{prefix}{parts[0]}"
                if skill_dir not in seen:
                    seen.add(skill_dir)
                    skill_dirs.append(skill_dir)
        results = []
        for skill_dir in skill_dirs:
            entry = _fetch_skill_md(repo, branch, skill_dir)
            if entry:
                results.append(entry)
        return results

    all_entries: list = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_crawl_repo, repo, paths): repo
            for repo, paths in by_repo.items()
        }
        for future in as_completed(futures):
            repo = futures[future]
            try:
                all_entries.extend(future.result())
            except Exception as e:
                print(f"    Warning: curated tap {repo}: {e}", file=sys.stderr)

    elapsed = time.time() - start
    print(
        f"  curated taps: {len(all_entries)} skills from {len(by_repo)} repos "
        f"({elapsed:.1f}s)",
        flush=True,
    )
    return all_entries


def batch_resolve_paths(skills: list, auth: GitHubAuth) -> list:
    """Resolve GitHub paths for skills.sh entries using batch tree lookups.

    Instead of resolving each skill individually (N×M API calls), we:
    1. Group skills by repo
    2. Fetch one tree per repo (2 API calls per repo)
    3. Find all SKILL.md files in the tree
    4. Match skills to their resolved paths
    """
    # Filter to skills.sh entries that need resolution
    skills_sh = [s for s in skills if s["source"] in {"skills.sh", "skills-sh"}]
    if not skills_sh:
        return skills

    print(f"  Resolving paths for {len(skills_sh)} skills.sh entries...",
          flush=True)
    start = time.time()

    # Group by repo
    by_repo: dict[str, list] = defaultdict(list)
    for s in skills_sh:
        repo = s.get("repo", "")
        if repo:
            by_repo[repo].append(s)

    print(f"    {len(by_repo)} unique repos to scan", flush=True)

    resolved_count = 0

    # Fetch trees in parallel (up to 6 concurrent)
    def _resolve_repo(repo: str, entries: list):
        tree = _fetch_repo_tree(repo, auth)
        if not tree:
            return 0

        # Find all SKILL.md paths in this repo
        skill_paths = {}  # skill_dir_name -> full_path
        for item in tree:
            if item.get("type") != "blob":
                continue
            path = item.get("path", "")
            if path.endswith("/SKILL.md"):
                skill_dir = path[: -len("/SKILL.md")]
                dir_name = skill_dir.split("/")[-1]
                skill_paths[dir_name.lower()] = f"{repo}/{skill_dir}"

                # Also check SKILL.md frontmatter name if we can match by path
                # For now, just index by directory name
            elif path == "SKILL.md":
                # Root-level SKILL.md
                skill_paths["_root_"] = f"{repo}"

        count = 0
        for entry in entries:
            # Try to match the skill's name/path to a tree entry
            skill_name = entry.get("name", "").lower()
            skill_path = entry.get("path", "").lower()
            identifier = entry.get("identifier", "")

            # Extract the skill token from the identifier
            # e.g. "skills-sh/d4vinci/scrapling/scrapling-official" -> "scrapling-official"
            parts = identifier.replace("skills-sh/", "").replace("skills.sh/", "")
            skill_token = parts.split("/")[-1].lower() if "/" in parts else ""

            # Try matching in order of likelihood
            for candidate in [skill_token, skill_name, skill_path]:
                if not candidate:
                    continue
                matched = skill_paths.get(candidate)
                if matched:
                    entry["resolved_github_id"] = matched
                    count += 1
                    break
            else:
                # Try fuzzy: skill_token with common transformations
                for tree_name, tree_path in skill_paths.items():
                    if (skill_token and (
                        tree_name.replace("-", "") == skill_token.replace("-", "")
                        or skill_token in tree_name
                        or tree_name in skill_token
                    )):
                        entry["resolved_github_id"] = tree_path
                        count += 1
                        break

        return count

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(_resolve_repo, repo, entries): repo
            for repo, entries in by_repo.items()
        }
        for future in as_completed(futures):
            try:
                resolved_count += future.result()
            except Exception as e:
                repo = futures[future]
                print(f"    Warning: {repo}: {e}", file=sys.stderr)

    elapsed = time.time() - start
    print(f"  Resolved {resolved_count}/{len(skills_sh)} paths ({elapsed:.1f}s)",
          flush=True)
    return skills


def main():
    print("Building Fabric Skills Index...", flush=True)
    overall_start = time.time()

    auth = GitHubAuth()
    print(f"GitHub auth: {auth.auth_method()}")
    if auth.auth_method() == "anonymous":
        print("WARNING: No GitHub authentication — rate limit is 60/hr. "
              "Set GITHUB_TOKEN for better results.", file=sys.stderr)

    skills_sh_source = SkillsShSource(auth=auth)
    sources = {
        "official": OptionalSkillSource(),
        "well-known": WellKnownSkillSource(),
        "github": GitHubSource(auth=auth),
        "clawhub": ClawHubSource(),
        "claude-marketplace": ClaudeMarketplaceSource(auth=auth),
        "lobehub": LobeHubSource(),
        "browse-sh": BrowseShSource(),
    }

    all_skills: list[dict] = []

    # Crawl skills.sh
    all_skills.extend(crawl_skills_sh(skills_sh_source))

    # Crawl other sources in parallel.
    # Per-source soft caps — sources stop returning when they run out, so these
    # are ceilings, not targets.  ClawHub has 20k+ skills; bumping to 100k
    # (well above current catalog size) lets the full catalog land in the
    # index instead of being truncated at an arbitrary build-time limit.
    SOURCE_LIMITS = {
        # 0 = unbounded catalog walk (max_items=0 in ClawHubSource). A positive
        # limit bounds the walk and also enables the interactive 12s budget.
        "clawhub": 0,
        "lobehub": 100_000,
        "browse-sh": 5_000,
        "claude-marketplace": 5_000,
        "github": 5_000,
        "well-known": 5_000,
        "official": 5_000,
    }
    DEFAULT_SOURCE_LIMIT = 500

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {}
        for name, source in sources.items():
            limit = SOURCE_LIMITS.get(name, DEFAULT_SOURCE_LIMIT)
            futures[pool.submit(crawl_source, source, name, limit)] = name
        for future in as_completed(futures):
            try:
                all_skills.extend(future.result())
            except Exception as e:
                print(f"  Error: {e}", file=sys.stderr)

    # Curated ecosystem taps — tree-based crawl, cheap on API quota
    all_skills.extend(crawl_curated_taps(auth, sources["github"]))

    # Batch resolve GitHub paths for skills.sh entries
    all_skills = batch_resolve_paths(all_skills, auth)

    # Collect which sources hit a GitHub API rate limit during the crawl.
    # github / claude-marketplace / well-known all read api.github.com, so a
    # rate-limited token zeroes all three at once — surfaced below so the
    # failure message names the real cause instead of "source returned 0".
    rate_limited_sources = {
        name for name, source in sources.items()
        if getattr(source, "is_rate_limited", False)
    }
    if rate_limited_sources:
        print(
            "  WARNING: GitHub API rate limit hit for: "
            + ", ".join(sorted(rate_limited_sources)),
            file=sys.stderr,
        )

    # Deduplicate by identifier
    seen: dict[str, dict] = {}
    for skill in all_skills:
        key = skill["identifier"]
        if key not in seen:
            seen[key] = skill
    deduped = list(seen.values())

    # Sort
    source_order = {"official": 0, "skills-sh": 1, "skills.sh": 1,
                    "github": 2, "well-known": 3, "clawhub": 4,
                    "browse-sh": 5, "claude-marketplace": 6, "lobehub": 7}
    deduped.sort(key=lambda s: (source_order.get(s["source"], 99), s["name"]))

    from collections import Counter
    by_source = Counter(s["source"] for s in deduped)
    print(f"\nCrawled {len(deduped)} skills in {time.time() - overall_start:.0f}s")
    for src, count in sorted(by_source.items(), key=lambda x: -x[1]):
        resolved = sum(1 for s in deduped
                       if s["source"] == src and s.get("resolved_github_id"))
        extra = f" ({resolved} resolved)" if resolved else ""
        print(f"  {src}: {count}{extra}")

    # Health check: catch silent breakage early. Every source listed below
    # has historically returned at least `floor` entries; a zero (or near-
    # zero) result almost certainly means a tap path moved, an API changed,
    # or rate limiting kicked in.  Failing here forces a human look before
    # the broken index reaches the live docs.
    EXPECTED_FLOORS = {
        # skills.sh now uses the sitemap walker (~20k catalog as of May 2026).
        # Anything under 10k means the sitemap shape changed or fetches failed
        # — better to fail loudly than ship a regression to the 858-skill
        # popular-queries era.
        "skills.sh": 10000,
        "lobehub": 100,
        # ClawHub had 49,698+ skills as of May 2026 — anything under 20k means
        # pagination broke or the API surface changed.  Fail loudly rather
        # than ship a degenerate index (we shipped 200/50000 silently for
        # weeks because the floor was 50).
        "clawhub": 20000,
        "official": 50,
        # Collapsed across all GitHub taps: the default runtime taps alone
        # historically return 300+, and the curated ecosystem taps
        # (CURATED_TAPS) add ~2,000 more. Anything under 500 means the tap
        # crawl or the curated tree walk broke.
        "github": 500,
        "browse-sh": 50,
    }
    health_errors = []
    for src, floor in EXPECTED_FLOORS.items():
        # 'skills-sh' and 'skills.sh' are the same source; both labels exist.
        count = by_source.get(src, 0)
        if src == "skills.sh":
            count = by_source.get("skills.sh", 0) + by_source.get("skills-sh", 0)
        if count < floor:
            health_errors.append(f"  {src}: {count} < expected floor {floor}")

    MIN_TOTAL = 1500
    if len(deduped) < MIN_TOTAL:
        health_errors.append(
            f"  total: {len(deduped)} < expected floor {MIN_TOTAL}"
        )

    if health_errors:
        print(
            "\nERROR: skills index health check failed — refusing to ship "
            "a degenerate index. Investigate the following sources:",
            file=sys.stderr,
        )
        for line in health_errors:
            print(line, file=sys.stderr)
        if rate_limited_sources:
            print(
                "\nGitHub API rate limit was hit during this crawl for: "
                + ", ".join(sorted(rate_limited_sources))
                + ". This is the usual cause of an all-GitHub-tap collapse "
                "(github / claude-marketplace / well-known dropping to zero "
                "together). Re-run with a higher-quota GITHUB_TOKEN.",
                file=sys.stderr,
            )
        print(
            "\nIf the drop is expected (e.g. a hub is genuinely shutting "
            "down), lower the floor in scripts/build_skills_index.py "
            "EXPECTED_FLOORS in the same PR.",
            file=sys.stderr,
        )
        # IMPORTANT: do NOT write OUTPUT_PATH on failure. The index file is
        # gitignored, so a fresh deploy checkout has no copy on disk — leaving
        # it absent lets website/scripts/extract-skills.py fall back to the
        # legacy snapshot cache (or skip the unified index) instead of reading
        # a degenerate file. Writing-then-exiting-2 was the bug that shipped an
        # index with every GitHub-API source dropped to zero: deploy-site.yml
        # swallows the exit code with `|| echo non-fatal`, and the partial file
        # was already on disk for extract-skills to pick up.
        sys.exit(2)

    # Healthy — only now write the index out for the docs build to consume.
    index = {
        "version": INDEX_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "skill_count": len(deduped),
        "skills": deduped,
    }
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, separators=(",", ":"), ensure_ascii=False)
    file_size = os.path.getsize(OUTPUT_PATH)
    print(f"\nDone! {len(deduped)} skills indexed in "
          f"{time.time() - overall_start:.0f}s")
    print(f"Output: {OUTPUT_PATH} ({file_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
