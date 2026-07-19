---
sidebar_position: 7
title: "Skills Ecosystem Directory"
description: "Curated, trust-tiered map of the wider agent-skills ecosystem indexed by Fabric"
---

# Skills Ecosystem Directory

This directory is a curated, trust-tiered map of the wider agent-skills ecosystem — **312 sources** as of 2026-07-16 — covering first-party vendor skill repositories, expert skill packs, community marketplaces, MCP registries, authoritative data sources, and research references. It complements the [Bundled Skills Catalog](/reference/skills-catalog) and [Optional Skills Catalog](/reference/optional-skills-catalog): those list skills that ship with Fabric, while this page maps where the rest of the ecosystem lives.

Validated skill-pack repositories from this directory feed the unified skills index as curated taps (`scripts/build_skills_index.py`), so their skills surface in `fabric skills search` and the [Skills Hub](/skills). Listing here is an index entry with a governance policy, **not** an endorsement: nothing is auto-installed, and every install passes the skills guard security scan and quarantine review first. A machine-readable copy of this directory is served at `/api/skills-sources.json`.

## Trust tiers

| Tier | Meaning |
|------|---------|
| **A1** | Verified first-party, government, standards, or canonical ecosystem source. Still requires per-version license and security review. |
| **A2** | Recognized expert, academic, or specialist-maintained source with strong signal and explicit methodology. |
| **B** | Useful maintained community source or aggregator. Import only after canonical-source, provenance, license, and evaluation checks. |
| **C** | Experimental, niche, derived, or immature source. Index for research; manual promotion only. |
| **Q** | Quarantine/discovery-only. Never auto-install, execute, or mirror. |

Tier and wave assignments are review outcomes from the source survey, not endorsements. Every skill still requires per-version license and security review at install time.

## First-wave sources (30)

The recommended starting set: the highest-signal sources across company building, product, design, engineering, marketing, science, legal, video, and directory infrastructure.

| Source | Tier | Categories | Why it matters | License note |
|--------|------|------------|----------------|--------------|
| [Agent Skills specification](https://agentskills.io) | A1 | directory infrastructure, standards | Use this as the normalization target for all imported or synthesized skills. | Open specification; verify site terms |
| [anthropics/skills](https://github.com/anthropics/skills) | A1 | documents, design, software engineering, enterprise communication | Canonical first-party examples of the open Agent Skills format. | Mixed: many skills Apache-2.0; document skills are source-available with additional terms |
| [jgraph/drawio-mcp](https://github.com/jgraph/drawio-mcp) | A1 | diagrams, architecture, process mapping | Direct execution layer for CAD, BIM, or diagram skills; pair with constrained procedural skills and approval checkpoints. | Verify at ingest |
| [remotion-dev/skills](https://github.com/remotion-dev/skills) | A1 | video, motion design, content production | First-party best practices for programmatic video and motion design. | Verify at ingest |
| [skills.sh](https://skills.sh) | A1 | directory infrastructure, discovery, security | Best current ingestion spine for a live directory; avoid freezing a one-time scrape. | Website/API terms apply |
| [vercel-labs/skills](https://github.com/vercel-labs/skills) | A1 | directory infrastructure, discovery, developer productivity | Provides the widely used find-skills/install workflow and cross-harness routing. | Verify at ingest |
| [AgentSkillOS](https://arxiv.org/abs/2603.02176) | A2 | directory infrastructure, orchestration, evaluation | Use to design ingestion, evaluation, permissions, and orchestration—not as an installable skill. | Paper terms apply |
| [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp) | A2 | 3D, video, design, CAD | Direct execution layer for CAD, BIM, or diagram skills; pair with constrained procedural skills and approval checkpoints. | MIT |
| [bevibing/tutor-skills](https://github.com/bevibing/tutor-skills) | A2 | education, tutoring, knowledge management, active recall | Good concrete learning loop: source mapping, structured notes, practice questions, diagnostics, weak-area drills, and tracked mastery. | MIT |
| [Contractual Skills / GovernSpec](https://arxiv.org/abs/2605.22634) | A2 | governance, compliance, skill specification | Use to design ingestion, evaluation, permissions, and orchestration—not as an installable skill. | Paper terms apply |
| [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) | A2 | marketing, SEO, copywriting, content | Covers strategy and execution: audits, positioning, copy, psychology, content, programmatic SEO, ads, lifecycle email, cold outreach, churn, and revenue operat… | Verify at ingest |
| [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) | A2 | software engineering, simplicity, code review, technical debt | Encodes a practical ladder: reuse, standard library, existing dependency, then the minimum new code—without dropping security or accessibility. | MIT |
| [EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin) | A2 | software engineering, product development, planning, code review | Strong model for turning each completed project into reusable institutional knowledge. | MIT |
| [garrytan/gstack](https://github.com/garrytan/gstack) | A2 | company building, product, software engineering, design | Broad, coherent role system with a Think → Plan → Build → Review → Test → Ship → Reflect process. | MIT |
| [harvard-lil/lawskills-hub](https://github.com/harvard-lil/lawskills-hub) | A2 | legal education, tutoring, legal research coaching, professional development | Unusually strong safety constraints, rubrics, anti-patterns, test scenarios, trace logs, and no-skill baselines. | TBD |
| [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) | A2 | video, scriptwriting, motion graphics, product launch | High-value production layer alongside Remotion, Runway, ElevenLabs, and Deepgram. | Verify at ingest |
| [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | A2 | life science, medicine, drug discovery, clinical research | Best single open source for broad scientific and healthcare coverage, including multi-omics, medical imaging, grants, regulatory workflows, simulation, and lab… | MIT |
| [leonxlnx/taste-skill](https://github.com/leonxlnx/taste-skill) | A2 | design, frontend, typography, motion | High-signal collection for layout, typography, spacing, motion, redesign, brand kits, and visual-direction enforcement. | MIT |
| [mattpocock/skills](https://github.com/mattpocock/skills) | A2 | software engineering, product, writing, teaching | A strong example of small, sharply triggered skills rather than oversized universal prompts. | MIT |
| [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp) | A2 | CAD, 3D, mechanical engineering | Direct execution layer for CAD, BIM, or diagram skills; pair with constrained procedural skills and approval checkpoints. | MIT/verify |
| [obra/superpowers](https://github.com/obra/superpowers) | A2 | software engineering, planning, testing, debugging | One of the clearest composable workflow systems: plans, worktrees, TDD, review, debugging, verification, and parallel agents. | MIT |
| [OpenSkillEval](https://arxiv.org/abs/2605.23657) | A2 | evaluation, artifacts, design | Use to design ingestion, evaluation, permissions, and orchestration—not as an installable skill. | Paper terms apply |
| [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | A2 | design, frontend, visual critique, polish | Useful verbs such as critique, clarify, optimize, colorize, delight, distill, and quiet make it a strong finishing layer. | Verify at ingest |
| [phuryn/pm-skills](https://github.com/phuryn/pm-skills) | A2 | product management, discovery, strategy, market research | Strong coverage of discovery, assumptions, experiments, JTBD, roadmaps, PRDs, pricing, metrics, growth, and launch. | MIT |
| [shawnpang/startup-founder-skills](https://github.com/shawnpang/startup-founder-skills) | A2 | fundraising, sales, product, recruiting | One of the strongest direct matches for pitch decks, investor research, data rooms, outreach, accelerators, SOPs, board updates, product, sales, recruiting, an… | MIT |
| [Show2Instruct/ifc-bonsai-mcp](https://github.com/Show2Instruct/ifc-bonsai-mcp) | A2 | BIM, architecture, construction, IFC | Direct execution layer for CAD, BIM, or diagram skills; pair with constrained procedural skills and approval checkpoints. | Verify at ingest |
| [SkillMutator](https://arxiv.org/abs/2606.14154) | A2 | security, evaluation | Use to design ingestion, evaluation, permissions, and orchestration—not as an installable skill. | Paper terms apply |
| [SWE-Skills-Bench](https://arxiv.org/abs/2603.15401) | A2 | evaluation, software engineering | Use to design ingestion, evaluation, permissions, and orchestration—not as an installable skill. | Paper terms apply |
| [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills) | B | product, marketing, operations, C-suite | Useful raw material across product, marketing, research operations, regulatory/quality management, C-suite roles, operations, commercial strategy, finance, and… | MIT reported by repository; verify per imported file and original provenance |
| [lawve-ai/awesome-legal-skills](https://github.com/lawve-ai/awesome-legal-skills) | B | legal, AI governance, privacy, contracts | Broadest focused legal catalog found, including jurisdiction-specific skills, legal operations, verification, privacy, and AI regulation. | Collection: CC BY-NC-ND 4.0; each skill may have separate terms |

## Wave 2 sources (173)

Mostly first-party vendor skill repositories plus specialist packs — canonical workflows maintained by the product teams themselves.

| Source | Tier | Type | Categories | License/status |
|--------|------|------|------------|----------------|
| [allenai/asta-plugins](https://github.com/allenai/asta-plugins) | A1 | first-party skill or agent repository | AI, ML, Data Science & Research | Verify at ingest |
| [anthropics/knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins) | A1 | first-party skill or agent repository | Copywriting & Conversion Writing, Creative Direction & Brand Systems, Customer Support And Service Operations | Verify at ingest |
| [antvis/chart-visualization-skills](https://github.com/antvis/chart-visualization-skills) | A1 | first-party skill or agent repository | Databases, Data Engineering, Analytics, Spreadsheets, and Visualization | Verify at ingest |
| [apify/agent-skills](https://github.com/apify/agent-skills) | A1 | first-party skill or agent repository | web scraping, automation | Verify at ingest |
| [apollographql/skills](https://github.com/apollographql/skills) | A1 | first-party skill or agent repository | software engineering, APIs, GraphQL | Verify at ingest |
| [astronomer/agents](https://github.com/astronomer/agents) | A1 | first-party skill or agent repository | data engineering, workflow orchestration | Verify at ingest |
| [auth0/agent-skills](https://github.com/auth0/agent-skills) | A1 | first-party skill or agent repository | identity, security, authentication | Verify at ingest |
| [automattic/agent-skills](https://github.com/automattic/agent-skills) | A1 | first-party skill or agent repository | publishing, open source, content | Verify at ingest |
| [aws-samples/sample-drawio-mcp](https://github.com/aws-samples/sample-drawio-mcp) | A1 | MCP sample | diagrams, cloud architecture | Verify at ingest |
| [aws/agent-toolkit-for-aws](https://github.com/aws/agent-toolkit-for-aws) | A1 | first-party skill or agent repository | Cloud, DevOps, SRE | Verify at ingest |
| [axiomhq/skills](https://github.com/axiomhq/skills) | A1 | first-party skill or agent repository | observability, operations | Verify at ingest |
| [base/skills](https://github.com/base/skills) | A1 | first-party skill or agent repository | web3, payments, software engineering | Verify at ingest |
| [better-auth/skills](https://github.com/better-auth/skills) | A1 | first-party skill or agent repository | identity, authentication, software engineering | Verify at ingest |
| [bitwarden/ai-plugins](https://github.com/bitwarden/ai-plugins) | A1 | first-party skill or agent repository | security, secrets management | Verify at ingest |
| [box/box-for-ai](https://github.com/box/box-for-ai) | A1 | first-party skill or agent repository | documents, enterprise content, knowledge management | Verify at ingest |
| [brave/brave-search-skills](https://github.com/brave/brave-search-skills) | A1 | first-party skill or agent repository | search, research | Verify at ingest |
| [browser-use/browser-use](https://github.com/browser-use/browser-use) | A1 | first-party skill or agent repository | browser automation, web research | Verify at ingest |
| [browserbase/skills](https://github.com/browserbase/skills) | A1 | first-party skill or agent repository | browser automation, testing | Verify at ingest |
| [callstackincubator/agent-skills](https://github.com/callstackincubator/agent-skills) | A1 | first-party skill or agent repository | mobile development, software engineering | Verify at ingest |
| [clerk/skills](https://github.com/clerk/skills) | A1 | first-party skill or agent repository | identity, authentication | Verify at ingest |
| [clickhouse/agent-skills](https://github.com/clickhouse/agent-skills) | A1 | first-party skill or agent repository | databases, analytics | Verify at ingest |
| [cloudflare/skills](https://github.com/cloudflare/skills) | A1 | first-party skill or agent repository | cloud, edge, security, deployment | Verify at ingest |
| [coderabbitai/skills](https://github.com/coderabbitai/skills) | A1 | first-party skill or agent repository | code review, software engineering | Verify at ingest |
| [Congress.gov API](https://api.congress.gov) | A1 | authoritative reference to package | government, legislation, legal | Public information; site/API terms apply |
| [contentful/skills](https://github.com/contentful/skills) | A1 | first-party skill or agent repository | content, CMS, marketing | Verify at ingest |
| [contentstack/contentstack-agent-skills](https://github.com/contentstack/contentstack-agent-skills) | A1 | first-party skill or agent repository | content, CMS, marketing | Verify at ingest |
| [convex-dev/convex](https://github.com/convex-dev/convex) | A1 | first-party skill or agent repository | backend, databases, software engineering | Verify at ingest |
| [cypress-io/ai-toolkit](https://github.com/cypress-io/ai-toolkit) | A1 | first-party skill or agent repository | Software Testing and QA | Verify at ingest |
| [dagster-io/skills](https://github.com/dagster-io/skills) | A1 | first-party skill or agent repository | data engineering, workflow orchestration | Verify at ingest |
| [dash0hq/agent-skills](https://github.com/dash0hq/agent-skills) | A1 | first-party skill or agent repository | observability, operations | Verify at ingest |
| [Data.gov API](https://api.data.gov) | A1 | authoritative reference to package | government, open data | Public information; site/API terms apply |
| [databricks/databricks-agent-skills](https://github.com/databricks/databricks-agent-skills) | A1 | first-party skill or agent repository | Databases, Data Engineering, Analytics, Spreadsheets, and Visualization | Verify at ingest |
| [datadog-labs/agent-skills](https://github.com/datadog-labs/agent-skills) | A1 | first-party skill or agent repository | observability, operations | Verify at ingest |
| [dbt-labs/dbt-agent-skills](https://github.com/dbt-labs/dbt-agent-skills) | A1 | first-party skill or agent repository | analytics engineering, data | Verify at ingest |
| [deepgram/skills](https://github.com/deepgram/skills) | A1 | first-party skill or agent repository | audio, speech, content production | Verify at ingest |
| [denoland/skills](https://github.com/denoland/skills) | A1 | first-party skill or agent repository | software engineering, runtime | Verify at ingest |
| [dotnet/skills](https://github.com/dotnet/skills) | A1 | first-party skill or agent repository | Mobile and Desktop Product Engineering | Verify at ingest |
| [elevenlabs/skills](https://github.com/elevenlabs/skills) | A1 | first-party skill or agent repository | audio, voice, content production | Verify at ingest |
| [encoredev/skills](https://github.com/encoredev/skills) | A1 | first-party skill or agent repository | backend, cloud, software engineering | Verify at ingest |
| [exploreomni/omni-agent-skills](https://github.com/exploreomni/omni-agent-skills) | A1 | first-party skill or agent repository | analytics, business intelligence | Verify at ingest |
| [expo/skills](https://github.com/expo/skills) | A1 | first-party skill or agent repository | mobile development, software engineering | Verify at ingest |
| [facebook/react](https://github.com/facebook/react) | A1 | first-party skill or agent repository | frontend, software engineering | Verify at ingest |
| [factory-ai/factory-plugins](https://github.com/factory-ai/factory-plugins) | A1 | first-party skill or agent repository | software engineering, developer productivity | Verify at ingest |
| [Federal Register API](https://www.federalregister.gov/developers/documentation/api/v1) | A1 | authoritative reference to package | government, regulation, legal | Public information; site/API terms apply |
| [figma/mcp-server-guide](https://github.com/figma/mcp-server-guide) | A1 | first-party skill or agent repository | design, MCP, product development | Verify at ingest |
| [firebase/agent-skills](https://github.com/firebase/agent-skills) | A1 | first-party skill or agent repository | backend, cloud, mobile | Verify at ingest |
| [firecrawl/cli](https://github.com/firecrawl/cli) | A1 | first-party skill or agent repository | web scraping, research | Verify at ingest |
| [flutter/agent-plugins](https://github.com/flutter/agent-plugins) | A1 | first-party skill or agent repository | Mobile and Desktop Product Engineering | Verify at ingest |
| [flutter/skills](https://github.com/flutter/skills) | A1 | first-party skill or agent repository | mobile development, software engineering | Verify at ingest |
| [fluxcd/agent-skills](https://github.com/fluxcd/agent-skills) | A1 | first-party skill or agent repository | Cloud, DevOps, SRE | Verify at ingest |
| [getdex/agent-skills](https://github.com/getdex/agent-skills) | A1 | first-party skill or agent repository | Email Marketing, CRM, and Lifecycle Messaging | Verify at ingest |
| [getsentry/skills](https://github.com/getsentry/skills) | A1 | first-party skill or agent repository | observability, debugging | Verify at ingest |
| [GitGuardian/agent-skills](https://github.com/GitGuardian/agent-skills) | A1 | first-party skill or agent repository | Cybersecurity and technical compliance engineering | Verify at ingest |
| [github/awesome-copilot](https://github.com/github/awesome-copilot) | A1 | first-party skill or agent repository | software engineering, open source, developer productivity | Verify per file |
| [google-gemini/gemini-skills](https://github.com/google-gemini/gemini-skills) | A1 | first-party skill or agent repository | AI, developer productivity | Verify at ingest |
| [google-labs-code/stitch-skills](https://github.com/google-labs-code/stitch-skills) | A1 | first-party skill or agent repository | design, frontend, prototyping | Verify at ingest |
| [GovInfo developer resources](https://www.govinfo.gov/developers) | A1 | authoritative reference to package | government, legal, public records | Public information; site/API terms apply |
| [hashicorp/agent-skills](https://github.com/hashicorp/agent-skills) | A1 | first-party skill or agent repository | cloud, infrastructure, security | Verify at ingest |
| [HHS HIPAA for Professionals](https://www.hhs.gov/hipaa/for-professionals/index.html) | A1 | authoritative reference to package | HIPAA, healthcare compliance, privacy | Public information; site/API terms apply |
| [huggingface/skills](https://github.com/huggingface/skills) | A1 | first-party skill or agent repository | AI, machine learning, research | Verify at ingest |
| [kotlin/kotlin-agent-skills](https://github.com/kotlin/kotlin-agent-skills) | A1 | first-party skill or agent repository | software engineering, mobile, backend | Verify at ingest |
| [krayin/agent-skills](https://github.com/krayin/agent-skills) | A1 | first-party skill or agent repository | Email Marketing, CRM, and Lifecycle Messaging | Verify at ingest |
| [LambdaTest/agent-skills](https://github.com/LambdaTest/agent-skills) | A1 | first-party skill or agent repository | Software Testing and QA | Verify at ingest |
| [langchain-ai/langchain-skills](https://github.com/langchain-ai/langchain-skills) | A1 | first-party skill or agent repository | AI agents, software engineering | Verify at ingest |
| [langfuse/skills](https://github.com/langfuse/skills) | A1 | first-party skill or agent repository | AI observability, evaluation | Verify at ingest |
| [launchdarkly/agent-skills](https://github.com/launchdarkly/agent-skills) | A1 | first-party skill or agent repository | feature management, product operations | Verify at ingest |
| [livekit/agent-skills](https://github.com/livekit/agent-skills) | A1 | first-party skill or agent repository | voice agents, real-time media | Verify at ingest |
| [lottiefiles/motion-design-skill](https://github.com/lottiefiles/motion-design-skill) | A1 | first-party skill or agent repository | UX & UI Design | Verify at ingest |
| [makenotion/skills](https://github.com/makenotion/skills) | A1 | first-party skill or agent repository | knowledge management, documents, operations | Verify at ingest |
| [mapbox/mapbox-agent-skills](https://github.com/mapbox/mapbox-agent-skills) | A1 | first-party skill or agent repository | geospatial, housing, mapping | Verify at ingest |
| [mastra-ai/skills](https://github.com/mastra-ai/skills) | A1 | first-party skill or agent repository | AI agents, software engineering | Verify at ingest |
| [mcp-use/mcp-use](https://github.com/mcp-use/mcp-use) | A1 | first-party skill or agent repository | MCP, AI agents, software engineering | Verify at ingest |
| [medusajs/medusa-agent-skills](https://github.com/medusajs/medusa-agent-skills) | A1 | first-party skill or agent repository | ecommerce, software engineering | Verify at ingest |
| [microsoft/azure-skills](https://github.com/microsoft/azure-skills) | A1 | first-party skill or agent repository | cloud, infrastructure, enterprise | Verify at ingest |
| [microsoft/skills-for-fabric](https://github.com/microsoft/skills-for-fabric) | A1 | first-party skill or agent repository | Databases, Data Engineering, Analytics, Spreadsheets, and Visualization | Verify at ingest |
| [modelcontextprotocol/registry](https://github.com/modelcontextprotocol/registry) | A1 | MCP registry/directory | MCP, directory infrastructure, tool discovery | Per-server/package terms vary |
| [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | A1 | MCP registry/directory | MCP, directory infrastructure, tool discovery | Per-server/package terms vary |
| [n8n-io/n8n](https://github.com/n8n-io/n8n) | A1 | first-party skill or agent repository | automation, workflow orchestration, operations | Verify at ingest |
| [neondatabase/agent-skills](https://github.com/neondatabase/agent-skills) | A1 | first-party skill or agent repository | databases, software engineering | Verify at ingest |
| [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework) | A1 | authoritative reference to package | AI governance, risk, compliance | Public information; site/API terms apply |
| [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework) | A1 | authoritative reference to package | security, compliance, risk | Public information; site/API terms apply |
| [nuxt/ui](https://github.com/nuxt/ui) | A1 | first-party skill or agent repository | frontend, design systems | Verify at ingest |
| [nvidia/skills](https://github.com/nvidia/skills) | A1 | first-party skill or agent repository | AI, accelerated computing, science | Verify at ingest |
| [Official MCP Registry](https://registry.modelcontextprotocol.io) | A1 | MCP registry/directory | MCP, directory infrastructure, tool discovery | Per-server/package terms vary |
| [openai/skills](https://github.com/openai/skills) | A1 | first-party skill or agent repository | AI, software engineering, productivity | Verify per file |
| [openFDA APIs](https://open.fda.gov/apis/) | A1 | authoritative reference to package | healthcare, life science, regulation | Public information; site/API terms apply |
| [openshift/hypershift](https://github.com/openshift/hypershift) | A1 | first-party skill or agent repository | cloud, Kubernetes, infrastructure | Verify at ingest |
| [parallel-web/parallel-agent-skills](https://github.com/parallel-web/parallel-agent-skills) | A1 | first-party skill or agent repository | web research, search | Verify at ingest |
| [pinecone-io/skills](https://github.com/pinecone-io/skills) | A1 | first-party skill or agent repository | vector databases, AI | Verify at ingest |
| [planetscale/database-skills](https://github.com/planetscale/database-skills) | A1 | first-party skill or agent repository | databases, software engineering | Verify at ingest |
| [posthog/skills](https://github.com/posthog/skills) | A1 | first-party skill or agent repository | product analytics, growth, marketing | Verify at ingest |
| [preset-io/agent-skills](https://github.com/preset-io/agent-skills) | A1 | first-party skill or agent repository | Databases, Data Engineering, Analytics, Spreadsheets, and Visualization | Verify at ingest |
| [prisma/skills](https://github.com/prisma/skills) | A1 | first-party skill or agent repository | databases, software engineering | Verify at ingest |
| [projectopensea/opensea-skill](https://github.com/projectopensea/opensea-skill) | A1 | first-party skill or agent repository | web3, marketplaces | Verify at ingest |
| [pulumi/agent-skills](https://github.com/pulumi/agent-skills) | A1 | first-party skill or agent repository | infrastructure as code, cloud | Verify at ingest |
| [pytorch/pytorch](https://github.com/pytorch/pytorch) | A1 | first-party skill or agent repository | machine learning, science, software engineering | Verify at ingest |
| [redis/agent-skills](https://github.com/redis/agent-skills) | A1 | first-party skill or agent repository | databases, caching, software engineering | Verify at ingest |
| [Regulations.gov developers](https://www.regulations.gov/developers) | A1 | authoritative reference to package | government, regulation, public comments | Public information; site/API terms apply |
| [resend/resend-skills](https://github.com/resend/resend-skills) | A1 | first-party skill or agent repository | email, marketing, communications | Verify at ingest |
| [rivet-dev/skills](https://github.com/rivet-dev/skills) | A1 | first-party skill or agent repository | AI agents, software engineering | Verify at ingest |
| [runwayml/skills](https://github.com/runwayml/skills) | A1 | first-party skill or agent repository | video, generative media, content production | Verify at ingest |
| [sanity-io/agent-toolkit](https://github.com/sanity-io/agent-toolkit) | A1 | first-party skill or agent repository | content, CMS, marketing | Verify at ingest |
| [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | A1 | authoritative reference to package | finance, fundraising, public companies, regulation | Public information; site/API terms apply |
| [semgrep/skills](https://github.com/semgrep/skills) | A1 | first-party skill or agent repository | security, code review, compliance | Verify at ingest |
| [shopify/shopify-ai-toolkit](https://github.com/shopify/shopify-ai-toolkit) | A1 | first-party skill or agent repository | ecommerce, marketing, software engineering | Verify at ingest |
| [signoz/agent-skills](https://github.com/signoz/agent-skills) | A1 | first-party skill or agent repository | observability, operations | Verify at ingest |
| [streamlit/agent-skills](https://github.com/streamlit/agent-skills) | A1 | first-party skill or agent repository | data apps, analytics, software engineering | Verify at ingest |
| [stripe/ai](https://github.com/stripe/ai) | A1 | first-party skill or agent repository | finance, payments, software engineering | Verify at ingest |
| [supabase/agent-skills](https://github.com/supabase/agent-skills) | A1 | first-party skill or agent repository | backend, databases, software engineering | Verify at ingest |
| [sveltejs/ai-tools](https://github.com/sveltejs/ai-tools) | A1 | first-party skill or agent repository | frontend, software engineering | Verify at ingest |
| [tavily-ai/skills](https://github.com/tavily-ai/skills) | A1 | first-party skill or agent repository | search, research, AI agents | Verify at ingest |
| [temporalio/skill-temporal-developer](https://github.com/temporalio/skill-temporal-developer) | A1 | first-party skill or agent repository | workflow orchestration, backend | Verify at ingest |
| [tinybirdco/tinybird-agent-skills](https://github.com/tinybirdco/tinybird-agent-skills) | A1 | first-party skill or agent repository | data, analytics, APIs | Verify at ingest |
| [tldraw/tldraw](https://github.com/tldraw/tldraw) | A1 | first-party skill or agent repository | diagrams, design, collaboration | Verify at ingest |
| [triggerdotdev/skills](https://github.com/triggerdotdev/skills) | A1 | first-party skill or agent repository | automation, workflow orchestration | Verify at ingest |
| [upstash/context7](https://github.com/upstash/context7) | A1 | first-party skill or agent repository | documentation, software engineering | Verify at ingest |
| [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | A1 | first-party skill or agent repository | frontend, software engineering, design | Verify at ingest |
| [vercel/ai](https://github.com/vercel/ai) | A1 | first-party skill or agent repository | AI, frontend, software engineering | Verify at ingest |
| [webflow/webflow-skills](https://github.com/webflow/webflow-skills) | A1 | first-party skill or agent repository | web design, marketing, CMS | Verify at ingest |
| [whopio/whop-payments-network-skill](https://github.com/whopio/whop-payments-network-skill) | A1 | first-party skill or agent repository | payments, commerce, finance | Verify at ingest |
| [wix/skills](https://github.com/wix/skills) | A1 | first-party skill or agent repository | web design, marketing, commerce | Verify at ingest |
| [wordpress/agent-skills](https://github.com/wordpress/agent-skills) | A1 | first-party skill or agent repository | publishing, content, open source | Verify at ingest |
| [aaron-he-zhu/aaron-marketing-skills](https://github.com/aaron-he-zhu/aaron-marketing-skills) | A2 | expert skill pack | Social Media Strategy And Community Growth | Verify at ingest |
| [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) | A2 | expert skill pack | Frontend and web engineering, Software Engineering Lifecycle, UX & UI Design | Verify at ingest |
| [Agent Skills in the Wild](https://arxiv.org/abs/2601.10338) | A2 | research/evaluation reference | security, supply chain | Paper terms apply |
| [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo) | A2 | expert skill pack | Content Marketing And Editorial Strategy | Verify at ingest |
| [akin-ozer/cc-devops-skills](https://github.com/akin-ozer/cc-devops-skills) | A2 | expert skill pack | Cloud, DevOps, SRE | Verify at ingest |
| [antonbabenko/terraform-skill](https://github.com/antonbabenko/terraform-skill) | A2 | expert skill pack | Cloud, DevOps, SRE | Verify at ingest |
| [arvindrk/extract-design-system](https://github.com/arvindrk/extract-design-system) | A2 | specialized design skill | design systems, frontend, reverse engineering | Verify at ingest |
| [Attested Tool-Server Admission](https://arxiv.org/abs/2605.24248) | A2 | research/evaluation reference | MCP, security, compliance | Paper terms apply |
| [CadQuery/cadquery](https://github.com/CadQuery/cadquery) | A2 | reference/tool source to package | CAD, Python, manufacturing | Verify repository and dependency licenses |
| [dadederk/iOS-Accessibility-Agent-Skill](https://github.com/dadederk/iOS-Accessibility-Agent-Skill) | A2 | expert skill pack | UX & UI Design | Verify at ingest |
| [data-goblin/power-bi-agentic-development](https://github.com/data-goblin/power-bi-agentic-development) | A2 | expert skill pack | Databases, Data Engineering, Analytics, Spreadsheets, and Visualization | Verify at ingest |
| [deanpeters/Product-Manager-Skills](https://github.com/deanpeters/Product-Manager-Skills) | A2 | expert skill pack | Product Management and Strategy | Verify at ingest |
| [emilkowalski/skills](https://github.com/emilkowalski/skills) | A2 | expert design engineering pack | design, frontend, animation, interaction | Verify at ingest |
| [fayazara/macos-app-skills](https://github.com/fayazara/macos-app-skills) | A2 | expert skill pack | Mobile and Desktop Product Engineering | Verify at ingest |
| [FreeCAD/FreeCAD](https://github.com/FreeCAD/FreeCAD) | A2 | reference/tool source to package | CAD, mechanical engineering | Verify repository and dependency licenses |
| [github/opensource.guide](https://github.com/github/opensource.guide) | A2 | reference/tool source to package | open source, community building | Verify repository and dependency licenses |
| [higgsfield-ai/skills](https://github.com/higgsfield-ai/skills) | A2 | first-party generative-media skills | video, generative media, content production | Verify at ingest |
| [HL7/fhir](https://github.com/HL7/fhir) | A2 | reference/tool source to package | healthcare, standards, interoperability | Verify repository and dependency licenses |
| [jeffallan/claude-skills](https://github.com/jeffallan/claude-skills) | A2 | expert skill pack | Databases, Data Engineering, Analytics, Spreadsheets, and Visualization | Verify at ingest |
| [julianoczkowski/designer-skills](https://github.com/julianoczkowski/designer-skills) | A2 | expert skill pack | UX & UI Design | Verify at ingest |
| [jwynia/agent-skills](https://github.com/jwynia/agent-skills) | A2 | expert skill pack | Mobile and Desktop Product Engineering | Verify at ingest |
| [K-Dense-AI/claude-scientific-writer](https://github.com/K-Dense-AI/claude-scientific-writer) | A2 | scientific writing workflow | scientific writing, literature review, research communication | Verify at ingest |
| [Large-Scale MCP Implementations Dataset](https://arxiv.org/abs/2607.10123) | A2 | research/evaluation reference | MCP, datasets, discovery | Paper terms apply |
| [Malicious Or Not](https://arxiv.org/abs/2603.16572) | A2 | research/evaluation reference | security, provenance, supply chain | Paper terms apply |
| [mblode/agent-skills](https://github.com/mblode/agent-skills) | A2 | expert skill pack | UX & UI Design | Verify at ingest |
| [MCP Server Architecture Patterns](https://arxiv.org/abs/2606.30317) | A2 | research/evaluation reference | MCP, architecture, orchestration | Paper terms apply |
| [MCPZoo](https://arxiv.org/abs/2512.15144) | A2 | research/evaluation reference | MCP, datasets, security | Paper terms apply |
| [mermaid-js/mermaid](https://github.com/mermaid-js/mermaid) | A2 | reference/tool source to package | diagrams, documentation | Verify repository and dependency licenses |
| [mgifford/accessibility-skills](https://github.com/mgifford/accessibility-skills) | A2 | expert skill pack | UX & UI Design | Verify at ingest |
| [NeoLabHQ/context-engineering-kit](https://github.com/NeoLabHQ/context-engineering-kit) | A2 | expert skill pack | Software Testing and QA | Verify at ingest |
| [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) | A2 | reference/tool source to package | finance, market research, data | Verify repository and dependency licenses |
| [openscad/openscad](https://github.com/openscad/openscad) | A2 | reference/tool source to package | CAD, 3D, code-generated geometry | Verify repository and dependency licenses |
| [OpenSkill](https://arxiv.org/abs/2606.06741) | A2 | research/evaluation reference | self-improvement, evaluation, skill synthesis | Paper terms apply |
| [plantuml/plantuml](https://github.com/plantuml/plantuml) | A2 | reference/tool source to package | diagrams, software architecture | Verify repository and dependency licenses |
| [product-on-purpose/pm-skills](https://github.com/product-on-purpose/pm-skills) | A2 | expert skill pack | Product Management and Strategy | Verify at ingest |
| [Skill-to-LoRA](https://arxiv.org/abs/2606.16769) | A2 | research/evaluation reference | optimization, training, skills | Paper terms apply |
| [SkillScope: least privilege](https://arxiv.org/abs/2605.05868) | A2 | research/evaluation reference | security, permissions, least privilege | Paper terms apply |
| [softaworks/agent-toolkit](https://github.com/softaworks/agent-toolkit) | A2 | expert skill pack | Diagrams and technical visualization, Software Engineering Lifecycle | Verify at ingest |
| [synthetichealth/synthea](https://github.com/synthetichealth/synthea) | A2 | reference/tool source to package | healthcare, synthetic data, testing | Verify repository and dependency licenses |
| [TheCraigHewitt/skills](https://github.com/TheCraigHewitt/skills) | A2 | expert skill pack | B2B and B2C Sales | Verify at ingest |
| [todogroup/guides](https://github.com/todogroup/guides) | A2 | reference/tool source to package | open source, community building, program operations | Verify repository and dependency licenses |
| [uswds/uswds](https://github.com/uswds/uswds) | A2 | reference/tool source to package | government, design systems, accessibility | Verify repository and dependency licenses |
| [Aperivue/medsci-skills](https://github.com/Aperivue/medsci-skills) | B | medical science skill pack | medical science, de-identification, healthcare, scientific writing | Verify at ingest |
| [BrianRWagner/ai-marketing-claude-code-skills](https://github.com/BrianRWagner/ai-marketing-claude-code-skills) | B | marketing skill pack | marketing, cold outreach, social content, authority building | Verify at ingest |
| [KuangshiAi/SciVisAgentSkills](https://github.com/KuangshiAi/SciVisAgentSkills) | B | scientific visualization skill pack | scientific visualization, medical imaging, simulation, 3D | Verify at ingest |
| [LeadMagic/gtm-skills](https://github.com/LeadMagic/gtm-skills) | B | go-to-market skill pack | marketing, sales, go-to-market, lead generation | Verify at ingest |
| [LegalQuants/lq-skills](https://github.com/LegalQuants/lq-skills) | B | legal quantitative skill pack | legal, quantitative analysis, research | Verify at ingest |
| [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents) | B | cross-functional agent persona pack | company building, design, engineering, finance | MIT |
| [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | B | community design skill pack | design, frontend, UI/UX | Verify at ingest |
| [openclaw/openclaw](https://github.com/openclaw/openclaw) | B | agent runtime and skill host | agent infrastructure, automation, personal assistant, skills | MIT |
| [wshobson/agents](https://github.com/wshobson/agents) | B | large agent and skill marketplace | software engineering, architecture, security, data | MIT |

## Wave 3 sources (108)

Deeper reference material, domain tooling to package into skills, and niche or emerging community packs.

| Source | Tier | Type | Categories | License/status |
|--------|------|------|------------|----------------|
| [coinbase/agentic-wallet-skills](https://github.com/coinbase/agentic-wallet-skills) | A1 | first-party skill or agent repository | finance, web3, payments | Verify at ingest |
| [18F/guides](https://github.com/18F/guides) | A2 | reference/tool source to package | government, product, engineering, delivery | Verify repository and dependency licenses |
| [18F/handbook](https://github.com/18F/handbook) | A2 | reference/tool source to package | government, operations, people, open source | Verify repository and dependency licenses |
| [AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | A2 | reference/tool source to package | finance, AI, research | Verify repository and dependency licenses |
| [all-contributors/all-contributors](https://github.com/all-contributors/all-contributors) | A2 | reference/tool source to package | open source, community building, recognition | Verify repository and dependency licenses |
| [alphagov/govuk-design-system](https://github.com/alphagov/govuk-design-system) | A2 | reference/tool source to package | government, design systems, accessibility | Verify repository and dependency licenses |
| [build123d/build123d](https://github.com/build123d/build123d) | A2 | reference/tool source to package | CAD, Python, manufacturing | Verify repository and dependency licenses |
| [C4-PlantUML/C4-PlantUML](https://github.com/C4-PlantUML/C4-PlantUML) | A2 | reference/tool source to package | software architecture, C4, diagrams | Verify repository and dependency licenses |
| [chaoss/metrics](https://github.com/chaoss/metrics) | A2 | reference/tool source to package | open source, community health, analytics | Verify repository and dependency licenses |
| [CMSgov/bluebutton-server](https://github.com/CMSgov/bluebutton-server) | A2 | reference/tool source to package | healthcare, government, claims data | Verify repository and dependency licenses |
| [geopandas/geopandas](https://github.com/geopandas/geopandas) | A2 | reference/tool source to package | geospatial, Python, housing | Verify repository and dependency licenses |
| [hapifhir/hapi-fhir](https://github.com/hapifhir/hapi-fhir) | A2 | reference/tool source to package | healthcare, FHIR, interoperability | Verify repository and dependency licenses |
| [harvard-lil/capstone](https://github.com/harvard-lil/capstone) | A2 | reference/tool source to package | legal, case law, research | Verify repository and dependency licenses |
| [IfcOpenShell/IfcOpenShell](https://github.com/IfcOpenShell/IfcOpenShell) | A2 | reference/tool source to package | BIM, IFC, architecture, construction | Verify repository and dependency licenses |
| [KiCad/kicad-source-mirror](https://github.com/KiCad/kicad-source-mirror) | A2 | reference/tool source to package | electronics, PCB, CAD | Verify repository and dependency licenses |
| [LexPredict/lexpredict-lexnlp](https://github.com/LexPredict/lexpredict-lexnlp) | A2 | reference/tool source to package | legal, NLP, contracts | Verify repository and dependency licenses |
| [microsoft/qlib](https://github.com/microsoft/qlib) | A2 | reference/tool source to package | finance, machine learning, quant research | Verify repository and dependency licenses |
| [mingrammer/diagrams](https://github.com/mingrammer/diagrams) | A2 | reference/tool source to package | cloud architecture, diagrams, Python | Verify repository and dependency licenses |
| [OHDSI/CommonDataModel](https://github.com/OHDSI/CommonDataModel) | A2 | reference/tool source to package | healthcare, clinical data, research | Verify repository and dependency licenses |
| [openaddresses/openaddresses](https://github.com/openaddresses/openaddresses) | A2 | reference/tool source to package | housing, geospatial, address data | Verify repository and dependency licenses |
| [openstreetmap/openstreetmap-website](https://github.com/openstreetmap/openstreetmap-website) | A2 | reference/tool source to package | housing, geospatial, mapping | Verify repository and dependency licenses |
| [OSGeo/gdal](https://github.com/OSGeo/gdal) | A2 | reference/tool source to package | geospatial, remote sensing, housing | Verify repository and dependency licenses |
| [ossf/scorecard](https://github.com/ossf/scorecard) | A2 | reference/tool source to package | open source, security, supply chain | Verify repository and dependency licenses |
| [Project-MONAI/MONAI](https://github.com/Project-MONAI/MONAI) | A2 | reference/tool source to package | healthcare, medical imaging, machine learning | Verify repository and dependency licenses |
| [Project-OSRM/osrm-backend](https://github.com/Project-OSRM/osrm-backend) | A2 | reference/tool source to package | geospatial, routing, logistics | Verify repository and dependency licenses |
| [QuantConnect/Lean](https://github.com/QuantConnect/Lean) | A2 | reference/tool source to package | finance, quantitative research, backtesting | Verify repository and dependency licenses |
| [structurizr/dsl](https://github.com/structurizr/dsl) | A2 | reference/tool source to package | software architecture, C4, diagrams | Verify repository and dependency licenses |
| [terrastruct/d2](https://github.com/terrastruct/d2) | A2 | reference/tool source to package | diagrams, architecture | Verify repository and dependency licenses |
| [unitedstates/congress](https://github.com/unitedstates/congress) | A2 | reference/tool source to package | government, legislation, data | Verify repository and dependency licenses |
| [unitedstates/uscode](https://github.com/unitedstates/uscode) | A2 | reference/tool source to package | government, legal, legislation | Verify repository and dependency licenses |
| [101-skills/skills](https://github.com/101-skills/skills) | B | community skill collection | video, content production, design | Verify at ingest |
| [a5c-ai/babysitter](https://github.com/a5c-ai/babysitter) | B | community skill pack | Quality Management And Audit Operations | Verify at ingest |
| [borghei/Claude-Skills](https://github.com/borghei/Claude-Skills) | B | community skill pack | Email Marketing, CRM, and Lifecycle Messaging, Marketing Strategy & Go-To-Market, Risk Management And Incident Response | Verify at ingest |
| [cookiy-ai/user-research-skill](https://github.com/cookiy-ai/user-research-skill) | B | community skill pack | Customer Discovery & User Research | Verify at ingest |
| [digitalsamba/claude-code-video-toolkit](https://github.com/digitalsamba/claude-code-video-toolkit) | B | community skill pack | Video Production Craft | Verify at ingest |
| [FireRedTeam/FireRed-OpenStoryline](https://github.com/FireRedTeam/FireRed-OpenStoryline) | B | community skill pack | Video Post-Production | Verify at ingest |
| [FreedomIntelligence/OpenClaw-Medical-Skills](https://github.com/FreedomIntelligence/OpenClaw-Medical-Skills) | B | medical skill pack | medicine, healthcare, OpenClaw | Verify at ingest |
| [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills) | B | game-development skill directory | game development, 3D, art, software engineering | Verify at ingest |
| [Glama MCP directory](https://glama.ai/mcp/servers) | B | MCP registry/directory | MCP, directory infrastructure, tool discovery | Per-server/package terms vary |
| [gtmagents/gtm-agents](https://github.com/gtmagents/gtm-agents) | B | community skill pack | Copywriting & Conversion Writing | Verify at ingest |
| [itsmostafa/aws-agent-skills](https://github.com/itsmostafa/aws-agent-skills) | B | community skill pack | Cloud, DevOps, SRE | Verify at ingest |
| [lackeyjb/playwright-skill](https://github.com/lackeyjb/playwright-skill) | B | community skill pack | Software Testing and QA | Verify at ingest |
| [LukasNiessen/kubernetes-skill](https://github.com/LukasNiessen/kubernetes-skill) | B | community skill pack | Cloud, DevOps, SRE | Verify at ingest |
| [MCP.so](https://mcp.so) | B | MCP registry/directory | MCP, directory infrastructure, tool discovery | Per-server/package terms vary |
| [microsoft/win-dev-skills](https://github.com/microsoft/win-dev-skills) | B | community skill pack | Mobile and Desktop Product Engineering | Verify at ingest |
| [minhnv0807/ai-business-skills](https://github.com/minhnv0807/ai-business-skills) | B | community skill pack | Marketing Strategy & Go-To-Market | Verify at ingest |
| [mohitagw15856/pm-claude-skills](https://github.com/mohitagw15856/pm-claude-skills) | B | community skill pack | Community Building And Moderation | Verify at ingest |
| [mukul975/Anthropic-Cybersecurity-Skills](https://github.com/mukul975/Anthropic-Cybersecurity-Skills) | B | community skill pack | Cybersecurity and technical compliance engineering | Verify at ingest |
| [new-silvermoon/awesome-android-agent-skills](https://github.com/new-silvermoon/awesome-android-agent-skills) | B | community skill pack | Mobile and Desktop Product Engineering | Verify at ingest |
| [PulseMCP](https://www.pulsemcp.com) | B | MCP registry/directory | MCP, directory infrastructure, tool discovery | Per-server/package terms vary |
| [rampstackco/claude-skills](https://github.com/rampstackco/claude-skills) | B | community skill pack | Creative Direction & Brand Systems | Verify at ingest |
| [realkimbarrett/advertising-skills](https://github.com/realkimbarrett/advertising-skills) | B | community skill pack | Copywriting & Conversion Writing | Verify at ingest |
| [ruvnet/claude-flow](https://github.com/ruvnet/claude-flow) | B | community skill pack | Project, Program, and Portfolio Management | Verify at ingest |
| [SamurAIGPT/Generative-Media-Skills](https://github.com/SamurAIGPT/Generative-Media-Skills) | B | community generative-media pack | image, video, audio, content production | Verify at ingest |
| [sickn33/agentic-awesome-skills](https://github.com/sickn33/agentic-awesome-skills) | B | large community skill aggregator | software engineering, security, infrastructure, product | MIT reported for repository; verify every imported skill and upstream source |
| [Smithery](https://smithery.ai) | B | MCP registry/directory | MCP, directory infrastructure, tool discovery | Per-server/package terms vary |
| [Snakinya/MCPCorpus](https://github.com/Snakinya/MCPCorpus) | B | MCP registry/directory | MCP, directory infrastructure, tool discovery | Per-server/package terms vary |
| [spencerpauly/awesome-cursor-skills](https://github.com/spencerpauly/awesome-cursor-skills) | B | community skill pack | Frontend and web engineering | Verify at ingest |
| [spkane/freecad-addon-robust-mcp-server](https://github.com/spkane/freecad-addon-robust-mcp-server) | B | MCP tool server | CAD, 3D, mechanical engineering | Verify at ingest |
| [testdino-hq/playwright-skill](https://github.com/testdino-hq/playwright-skill) | B | community skill pack | Software Testing and QA | Verify at ingest |
| [timescale/pg-aiguide](https://github.com/timescale/pg-aiguide) | B | community skill pack | Databases, Data Engineering, Analytics, Spreadsheets, and Visualization | Verify at ingest |
| [wondelai/skills](https://github.com/wondelai/skills) | B | community skill pack | Creative Direction & Brand Systems | Verify at ingest |
| [yetone/native-feel-skill](https://github.com/yetone/native-feel-skill) | B | community skill pack | Mobile and Desktop Product Engineering | Verify at ingest |
| [AbdullahHameedKhan/karpathy-ponytail-skills](https://github.com/AbdullahHameedKhan/karpathy-ponytail-skills) | C | derived hybrid skill | software engineering, simplicity, code review | Verify at ingest |
| [aedev-tools/kling-3-prompting-skill](https://github.com/aedev-tools/kling-3-prompting-skill) | C | community skill pack | Video Production Craft | Verify at ingest |
| [Agents365-ai/excalidraw-skill](https://github.com/Agents365-ai/excalidraw-skill) | C | community skill pack | Diagrams and technical visualization | Verify at ingest |
| [Agents365-ai/mermaid-skill](https://github.com/Agents365-ai/mermaid-skill) | C | community skill pack | Diagrams and technical visualization | Verify at ingest |
| [Agents365-ai/plantuml-skill](https://github.com/Agents365-ai/plantuml-skill) | C | community skill pack | Diagrams and technical visualization | Verify at ingest |
| [Agile-V/agile_v_skills](https://github.com/Agile-V/agile_v_skills) | C | community skill pack | Quality Management And Audit Operations | Verify at ingest |
| [ahacker-1/cre-agent-skills](https://github.com/ahacker-1/cre-agent-skills) | C | commercial real-estate skill pack | housing, commercial real estate, underwriting, deal analysis | Verify at ingest |
| [aitytech/agentkits-marketing](https://github.com/aitytech/agentkits-marketing) | C | marketing agent kit | marketing, startups, content | Verify at ingest |
| [akseolabs-seo/cinematic-ui](https://github.com/akseolabs-seo/cinematic-ui) | C | community skill pack | Video Production Craft | Verify at ingest |
| [akshaykokane/Building-Customer-Service-Agent-with-Skill.md-and-Agent-Framework](https://github.com/akshaykokane/Building-Customer-Service-Agent-with-Skill.md-and-Agent-Framework) | C | community skill pack | Customer Support And Service Operations | Verify at ingest |
| [atc-net/atc-agentic-toolkit](https://github.com/atc-net/atc-agentic-toolkit) | C | community skill pack | Cybersecurity and technical compliance engineering | Verify at ingest |
| [awesome-genmedia/skills](https://github.com/awesome-genmedia/skills) | C | community skill pack | Video Production Craft | Verify at ingest |
| [charlsyd/blueprint-realtor-skills](https://github.com/charlsyd/blueprint-realtor-skills) | C | realtor skill pack | housing, real estate, sales, operations | Verify at ingest |
| [CodeAlive-AI/ceo-ai-os](https://github.com/CodeAlive-AI/ceo-ai-os) | C | community skill pack | CEO and Executive Operating Systems | Verify at ingest |
| [content-designer/ux-writing-skill](https://github.com/content-designer/ux-writing-skill) | C | community skill pack | Copywriting & Conversion Writing | Verify at ingest |
| [event4u-app/agent-config](https://github.com/event4u-app/agent-config) | C | mixed skill repository | fundraising, narrative, company building | Verify at ingest |
| [Hack23/homepage](https://github.com/Hack23/homepage) | C | community skill pack | Risk Management And Incident Response | Verify at ingest |
| [hiteshK03/video-production-skill](https://github.com/hiteshK03/video-production-skill) | C | community skill pack | Video Pre-Production | Verify at ingest |
| [igorrendulic/tg-customer-support-plugin](https://github.com/igorrendulic/tg-customer-support-plugin) | C | community skill pack | Customer Support And Service Operations | Verify at ingest |
| [kkunkunya/ppt-maker-agent-plugin](https://github.com/kkunkunya/ppt-maker-agent-plugin) | C | community skill pack | Presentations & Executive Communications | Verify at ingest |
| [konraddzbik/architecture-diagram-skill](https://github.com/konraddzbik/architecture-diagram-skill) | C | community skill pack | Diagrams and technical visualization | Verify at ingest |
| [lowesyang/fundraising-skill](https://github.com/lowesyang/fundraising-skill) | C | fundraising skill | fundraising, startups, investor relations | Verify at ingest |
| [LuoJiangYong/muse-video-skill](https://github.com/LuoJiangYong/muse-video-skill) | C | community skill pack | Video Pre-Production | Verify at ingest |
| [lycfyi/community-agent-plugin](https://github.com/lycfyi/community-agent-plugin) | C | community skill pack | Community Building And Moderation | Verify at ingest |
| [mikemai2awesome/agent-skills](https://github.com/mikemai2awesome/agent-skills) | C | community skill pack | UX & UI Design | Verify at ingest |
| [MLOps-Courses/mlops-coding-skills](https://github.com/MLOps-Courses/mlops-coding-skills) | C | community skill pack | AI, ML, Data Science & Research | Verify at ingest |
| [mukul975/privacy-data-protection-skills](https://github.com/mukul975/privacy-data-protection-skills) | C | community skill pack | Cybersecurity and technical compliance engineering | Verify at ingest |
| [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) | C | derived expert-inspired instructions | software engineering, AI, simplicity | MIT reported; verify |
| [murphye/agent-skills-customer-service](https://github.com/murphye/agent-skills-customer-service) | C | community skill pack | Customer Support And Service Operations | Verify at ingest |
| [nickzren/hipaa-foundation](https://github.com/nickzren/hipaa-foundation) | C | HIPAA workflow pack | HIPAA, healthcare compliance, privacy | Verify at ingest |
| [oakoss/agent-skills](https://github.com/oakoss/agent-skills) | C | community skill pack | Mobile and Desktop Product Engineering | Verify at ingest |
| [omkamal/pypict-claude-skill](https://github.com/omkamal/pypict-claude-skill) | C | community skill pack | Software Testing and QA | Verify at ingest |
| [oncesylvia/fundraising-skills](https://github.com/oncesylvia/fundraising-skills) | C | community skill pack | Startup Fundraising | Verify at ingest |
| [Overdrive-Consulting/vc-claude-starter-kit](https://github.com/Overdrive-Consulting/vc-claude-starter-kit) | C | venture-capital workflow kit | fundraising, venture capital, investment analysis | Verify at ingest |
| [pixeltable/pixeltable-skill](https://github.com/pixeltable/pixeltable-skill) | C | community skill pack | Databases, Data Engineering, Analytics, Spreadsheets, and Visualization | Verify at ingest |
| [psenger/ai-agent-skills](https://github.com/psenger/ai-agent-skills) | C | community skill pack | UX & UI Design | Verify at ingest |
| [realtyapi/realtyapi-skills](https://github.com/realtyapi/realtyapi-skills) | C | real-estate API skill pack | housing, real estate, property data, APIs | Verify at ingest |
| [rowanbrooks100/brand-strategy-skill](https://github.com/rowanbrooks100/brand-strategy-skill) | C | community skill pack | Marketing Strategy & Go-To-Market | Verify at ingest |
| [ScaleBrick/founder-marketing-skills](https://github.com/ScaleBrick/founder-marketing-skills) | C | community skill pack | Marketing Strategy & Go-To-Market | Verify at ingest |
| [TheProsperityAgent/prosperity-real-estate-skills](https://github.com/TheProsperityAgent/prosperity-real-estate-skills) | C | real-estate skill pack | housing, real estate, sales, marketing | Verify at ingest |
| [tjboudreaux/cc-skills-vc-fundraising](https://github.com/tjboudreaux/cc-skills-vc-fundraising) | C | community skill pack | Startup Fundraising | Verify at ingest |
| [tuanductran/hr-skills](https://github.com/tuanductran/hr-skills) | C | community skill pack | Organization Design And People Operations | Verify at ingest |
| [vaquarkhan/compliance-agent-skills](https://github.com/vaquarkhan/compliance-agent-skills) | C | compliance skill pack | compliance, HIPAA, security, governance | Verify at ingest |
| [wulaosiji/founder-skills](https://github.com/wulaosiji/founder-skills) | C | community skill pack | Startup Fundraising | Verify at ingest |

## Quarantined sources (1)

Indexed for awareness only. Never auto-install, execute, or mirror from these — known incidents include malicious submissions, credential theft, and abandoned-repository hijacking.

| Source | Tier | Type | Categories | Known risks |
|--------|------|------|------------|-------------|
| [ClawHub](https://clawhub.ai) | Q | community marketplace | discovery, OpenClaw | Known malicious submissions; Credential theft; Malware; Abandoned-repository hijacking |

## How sources are vetted

The ingestion pipeline every imported skill goes through before it can be recommended:

1. **Discover** — Pull skills.sh curated/official metadata, allowlisted repositories, official MCP registry, and approved community feeds.
2. **Canonicalize** — Resolve forks and copies to the original repository and exact skill path; record upstream attribution.
3. **Pin** — Fetch immutable commit/tag, compute SHA-256 for every file, and retain a content-addressed manifest.
4. **License gate** — Parse repository and file-level licenses. Index-only when redistribution or modification is unclear.
5. **Static review** — Parse SKILL.md, scripts, dependencies, URLs, install hooks, environment variables, and suspicious instructions.
6. **Cross-modal security** — Analyze natural-language instructions together with code/resources; run multiple scanners and repository-context checks.
7. **Sandbox execution** — Run without secrets, with deny-by-default network/filesystem/tool access; capture behavior and side effects.
8. **Domain evaluation** — Run realistic tasks with and without the skill; score correctness, quality, safety, token cost, and failure modes.
9. **Human approval** — Require domain experts for legal, healthcare, HIPAA, finance, housing, government, compliance, and high-impact actions.
10. **Publish signed version** — Publish immutable metadata and approved files; expose only least-privilege permissions and narrow triggers.
11. **Route structurally** — Retrieve through a capability tree and compose workflows as DAGs; do not load the whole catalog into context.
12. **Revalidate** — Re-run on upstream changes, model/tool changes, scanner updates, regulation changes, or reported incidents.

Non-negotiable rules:

1. **Popularity is not quality.** Promote a skill only after it beats the same agent without the skill on representative tasks.
2. **Repository trust is not skill trust.** Evaluate the exact path and immutable commit, including scripts, references, assets, install hooks, and transitive dependencies.
3. **No silent high-impact actions.** Payments, wallets, filings, messages, calendar or email changes, medical or legal conclusions, fabrication files, and production deployments require explicit approval.
4. **Do not flatten the catalog into context.** Retrieve narrowly and compose workflows explicitly.
5. **Respect licenses and provenance.** Index-only is the correct state when redistribution, derivatives, or commercial use is unclear.

## High-risk domains

| Domain | Default policy |
|--------|----------------|
| Legal and government | Information/research/coaching only by default; jurisdiction and effective-date fields required; mandatory source verification and human legal review before reliance. |
| Healthcare/HIPAA | No PHI leaves approved boundaries; de-identification tests; BAA/vendor controls where applicable; clinical decision support requires qualified human oversight. |
| Finance/fundraising | No autonomous trades, transfers, wallets, filings, or investor communications; transaction simulation and explicit approval gates. |
| Housing/real estate | Fair-housing and anti-discrimination checks; local licensing/law scope; no steering or protected-class inference; financial assumptions must be sourced. |
| CAD/BIM/manufacturing | Geometry/unit/constraint validation; simulation before fabrication; approval before exporting machine-ready or construction-ready files. |
| Marketing/community | Consent, platform terms, anti-spam, privacy, truthful claims, and brand-review gates. |
| Self-improvement/coaching | No diagnosis or crisis counseling; make limitations explicit; escalate medical/mental-health or safety issues to qualified support. |

## Proposing a source

To propose a new source, edit `website/static/api/skills-sources.json` and open a pull request with the canonical URL, publisher type, categories, license status, and known risk flags. New sources start at the lowest tier that fits the evidence and move up only after review — the pipeline above is the bar, not the paperwork.
