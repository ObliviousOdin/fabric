---
title: "Website Building"
sidebar_label: "Website Building"
description: "Plan, build, and launch complete websites — positioning and sitemap, page-by-page copywriting, stack selection, SEO and analytics setup, and deployment to a ..."
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Website Building

Plan, build, and launch complete websites — positioning and sitemap, page-by-page copywriting, stack selection, SEO and analytics setup, and deployment to a live URL. Use when the user wants a marketing site, landing page, portfolio, or docs site taken from idea to production.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/venture-studio/website-building` |
| Version | `1.0.0` |
| Author | Fabric |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `website`, `landing-page`, `seo`, `copywriting`, `deployment`, `marketing` |
| Related skills | [`webapp-development`](/user-guide/skills/bundled/venture-studio/venture-studio-webapp-development), [`rstack`](/user-guide/skills/bundled/venture-studio/venture-studio-rstack), [`design`](/user-guide/skills/bundled/creative/creative-design) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Fabric loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Website Building

Use this skill when the user wants a complete website carried from idea to a live URL — a marketing site, landing page, portfolio, product one-pager, or docs site. It owns the full arc: positioning, sitemap, page-by-page copywriting, stack selection, the build itself, technical SEO, analytics, and deployment. You are expected to actually build and ship with your code tools, not merely produce a plan.

Do not use this skill when the deliverable is an application — login, dashboards, stored user data, real business logic behind the pages; load `webapp-development` with skill_view for that. Do not use it for pure visual work on an existing page (a restyle, a component, a mockup); load `design` with skill_view directly. During any site build, visual direction — layout, type, color, spacing — routes to `design`; this skill decides what the pages say and how they ship.

## Workflow

Steps 1-3 are conversation and short documents. Steps 4-7 are the build. Step 8 is launch. Do not start step 4 until the user has approved the outputs of steps 1-3 — copy rewrites are cheap in markdown and expensive in markup.

1. **Position** — extract the one-liner, audience, and primary conversion action.
2. **Map** — draft the sitemap and a short brief per page; get explicit approval.
3. **Select the stack** — use the routing table below; default to the most boring option that fits.
4. **Write the copy** — a complete markdown draft per page, before any layout exists.
5. **Build** — scaffold, implement pages, route every visual decision through `design`.
6. **Harden** — technical SEO baseline, analytics wiring, performance pass.
7. **Deploy** — ship to a static host, connect the domain, verify the live URL.
8. **Launch** — run the checklist, then hand over repo, URL, and the update workflow.

## 1. Positioning before pixels

A site that cannot state what it is for will fail no matter how it looks. Before touching files, get answers to three questions — ask the user directly if the brief does not contain them:

- **One-liner.** What is this, for whom, and why should they care — one sentence a stranger understands. If the user cannot produce it, draft three candidates from what you know and let them pick or edit.
- **Audience.** The single primary reader. "Developers evaluating us against X" is an audience; "everyone" is not. Secondary audiences get pages, not the homepage hero.
- **Primary conversion action.** The one thing a visitor should do: sign up, book a call, install, subscribe, read the docs. Every page either advances this action or supports someone about to take it.

Capture the answers in a site brief and keep it in the repo — it is the contract every later copy decision is tested against:

```markdown
# Site brief: [project]

- **One-liner:**
- **Primary audience:**
- **Primary conversion action:**
- **Secondary actions:**
- **Proof assets on hand:** (customers, numbers, testimonials, press, stars)
- **Tone:** (two or three adjectives plus one example sentence)
- **Out of scope:**
```

## 2. Sitemap and page briefs

Start from the smallest sitemap that serves the conversion action. A typical product site: home, one page per major audience or use case, pricing, about or contact, and a blog or docs shell only if the user will actually feed it. Kill any page nobody owns.

For each page, write a four-line brief before any copy:

```markdown
## /pricing
- **Job:** convert evaluators who already believe the product works
- **Reader arrives from:** homepage CTA, search for "[product] pricing"
- **Must answer:** what does it cost, what is in each tier, can I try it free
- **CTA:** Start free trial
```

Present the sitemap plus briefs to the user as one short document. This is the cheapest moment in the whole project to change scope.

## 3. Stack selection

Pick by content shape and by who maintains the site after you leave, not by fashion.

| Option | Typical tools | Wins when | Wrong when |
|---|---|---|---|
| Hand-rolled static | plain HTML and CSS, zero build step | 1-3 pages, total control, longest shelf life | more than a handful of pages share layout |
| Static site generator | Astro, Eleventy, Hugo | content-heavy: markdown pages, blog, templating, near-zero JS by default | the site is really an app in disguise |
| Docs framework | Starlight, Docusaurus, MkDocs Material | docs with sidebar nav, search, versioning out of the box | marketing pages — they fight the theme |
| Meta-framework | Next.js, Nuxt, SvelteKit | interactive islands, existing team stack, code shared with the product app | pure content; you pay the complexity tax forever |
| Hosted no-code | Framer, Webflow, Carrd | user insists on editing visually with no repo | you cannot build or version it with code tools |

Defaults: a static site generator for almost every marketing site; hand-rolled for a single landing page; a docs framework for docs. Reach for a meta-framework only with a concrete interactive requirement — and if it is React-shaped, load `rstack` with skill_view for the house toolchain. If the user picks no-code, your role shrinks to strategy, copy, and SEO review — say so explicitly.

## 4. Copywriting

Write every page in full, in markdown, before building. Copy determines section structure; layout follows.

- **Specificity beats adjectives.** "Deploys in 90 seconds" beats "blazing fast". "Used by 3,200 teams" beats "trusted by industry leaders". Every adjective is a placeholder for a fact you have not found yet — find it or cut the sentence.
- **Every claim gets proof or gets cut.** A number, a name, a screenshot, a benchmark. Never fabricate proof: no invented testimonials, logos, or statistics. If proof assets are thin, say fewer things.
- **Write to one reader** in second person. "You ship faster", not "customers can experience accelerated delivery".
- **CTAs state the outcome**, not the mechanism: "Get the report", "Start deploying" — never "Submit" or "Learn more" as a primary action.
- **Front-load.** The first five words of a headline carry it; readers scan the left edge.
- **One idea per section.** If a section heading needs "and", split the section.
- **Ban list:** seamless, innovative, cutting-edge, world-class, revolutionary, next-generation, empower, unlock, supercharge. If the sentence survives their deletion they were noise; if not, it had no content.

**Landing-page anatomy** — sections in objection order, each existing to remove the next reason not to convert:

1. **Hero:** outcome headline (what the reader gets, not what the product is), one credibility subline (your sharpest proof point), primary CTA. All visible without scrolling.
2. **Show it:** screenshot, demo clip, or code sample. Readers do not believe a product they cannot see.
3. **How it works:** three or four steps, each one sentence.
4. **Proof:** logos used with permission, testimonials with full names and roles, concrete numbers. Weak proof is worse than none — omit rather than pad.
5. **Objection handling:** the two or three real reasons this reader hesitates — price, migration effort, security, lock-in — each answered head-on. An FAQ is the honest format when objections are many and small.
6. **Final CTA:** repeat the hero action for readers who scrolled the whole page. Do not introduce a new competing action here.

## 5. Build

- Scaffold with the chosen stack's own initializer; strip sample content before writing pages.
- Load `design` with skill_view before layout decisions, hand it the site brief and approved copy as the design brief, and follow its build-critique loop for the visual pass.
- Implement copy exactly as approved; propose edits back in markdown rather than silently rewording inside markup.
- Run the dev server and inspect every page at a phone width and a desktop width before calling the build done. A passing build is not visual verification.
- Commit at page granularity so the user can review history page by page.

## 6. Technical SEO and analytics

Bake this in before deploy — retrofitting metadata across a built site is tedious and error-prone.

**Per page:** a unique title (50-60 characters, most specific words first), a meta description (140-160 characters, written as ad copy for the click), a canonical URL, Open Graph tags (og:title, og:description, and an og:image at 1200x630 — generate a real image, links get shared with the preview), exactly one h1 matching search intent, heading levels that never skip, and descriptive alt text on meaningful images.

**Site-wide:** sitemap.xml (generators emit one; hand-rolled sites need it written), robots.txt that allows crawling and points at the sitemap, semantic landmarks (header, nav, main, and footer elements), a 404 page with navigation back in, and a favicon set.

**Performance:** images in modern formats with explicit width and height (layout shift is the classic failure), system fonts or self-hosted fonts with swap behavior, and a JS budget near zero for content pages. Audit from the terminal — for example `npx lighthouse [url] --output=json --quiet` — and treat scores under 90 on performance, accessibility, or SEO as build bugs.

**Analytics:** default to a lightweight privacy-respecting option (Plausible, Fathom, GoatCounter, or the host's built-in analytics) unless the user's org already standardizes on something heavier. Wire exactly one custom event: the primary conversion action from step 1. Verify it fires by triggering it yourself on the deployed site. No conversion event means the site's success is unmeasurable.

## 7. Deploy

Static output deploys anywhere; choose by where the repo lives and what the user already pays for. GitHub repo and no stated preference: Cloudflare Pages or GitHub Pages. Per-branch preview deployments matter: Netlify or Vercel. Existing cloud account: its static hosting plus CDN. All of these issue HTTPS certificates automatically.

For a custom domain, walk the user through the exact DNS records the host specifies, confirm the certificate issues, and check that apex and www resolve to one canonical origin with the other redirecting to it.

## 8. Launch checklist

Run every line against the production URL, not localhost. Deliver the completed checklist to the user.

```markdown
# Launch checklist: [url]

- [ ] Every sitemap page returns 200 over HTTPS
- [ ] Apex and www redirect to one canonical host
- [ ] All internal links and nav paths click through (crawl them, do not eyeball)
- [ ] Forms and CTAs work end to end on production
- [ ] Conversion event verified in the analytics dashboard
- [ ] Titles, descriptions, and canonicals unique per page
- [ ] OG preview checked with a link-preview debugger
- [ ] sitemap.xml and robots.txt reachable; sitemap submitted to search consoles
- [ ] Lighthouse performance, accessibility, SEO at 90+ on home and one deep page
- [ ] 404 page renders with working navigation
- [ ] Pages inspected at 375px and 1440px widths
- [ ] Repo pushed; user can edit copy and redeploy (document the two commands)
```

## Common failure modes

- **Pixels before positioning.** Building the hero before the one-liner exists guarantees a rewrite. The site brief comes first, every time.
- **Copy written inside the layout.** Wordsmithing in component files produces filler shaped to fit boxes. Draft in markdown, get approval, then build.
- **Adjective copy.** "Powerful, seamless, intuitive" describes nothing. If you cannot attach a number or a noun, the sentence is not done.
- **Fabricated proof.** Inventing testimonials, logos, or user counts to fill the proof section is never acceptable — thin honest proof beats fake proof.
- **App-in-disguise creep.** The moment the site needs accounts or per-user state, stop and switch to `webapp-development`; bolting auth onto a static generator ends badly.
- **Framework maximalism.** Shipping a client-side app framework to render five pages of prose. Content sites should be near-zero JS.
- **SEO as an afterthought.** Retrofitting titles, OG images, and canonicals across a finished site takes longer than putting them in the page template on day one.
- **Launching without the conversion event.** A live site with no measured conversion is a brochure nobody can evaluate. Wire and verify the event before announcing.
- **Declaring victory from a green build.** Deploy logs prove nothing about rendering. Open the production URL, click the nav, submit the form, check a phone width.
- **Orphaned handoff.** If the user cannot change a headline and redeploy without you, the project is not finished. Document the edit-preview-deploy loop in the repo readme.
