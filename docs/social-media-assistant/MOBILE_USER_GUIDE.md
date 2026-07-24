# Fabric Social — Mobile Operator Guide

**Audience:** GTM leads, founders, and content operators running company social growth from Fabric Mobile.
**First workflow:** LinkedIn Company Page, with manual publication and evidence-based reporting.

## What Fabric Social does

Fabric Social turns your daily social work into one operating loop:

```text
Set goal → choose today’s action → research/draft → human review →
post manually → capture proof → capture metrics → read report → learn → repeat
```

It helps you create and measure the work. It does not post automatically, guarantee LinkedIn distribution, or invent missing analytics.

### Current availability and proposed next stage

Fabric already provides **Social Studio** Compose/Library flows for drafting a LinkedIn post in chat and copying a post-ready caption. The persistent Social workspace in this guide is the proposed next stage: it adds goals, human approval, manual-publish proof, metrics, and reporting while preserving that existing drafting flow. Until it ships, do not assume the app already tracks publication or analytics.

## Before you start

Have these ready:

- your current company-page follower count;
- a target and target date (for example, 10,000 followers by a specific date);
- a working definition of what matters besides followers: impressions, qualified comments, clicks, qualified inbound leads, meetings, etc.;
- the person who approves company posts;
- your time zone and preferred SOD/EOD report times;
- company positioning, proof assets, customer-claim rules, and an initial competitor watchlist;
- access to LinkedIn analytics or a method to capture screenshots/exports after posting.

You can start without an API connection. In the first version, pasting a post URL and entering/uploading the numbers you can see is a supported, useful workflow.

---

## 1. Create your Social workspace

1. Open **Fabric Mobile** and connect to the Fabric gateway that will own this work.
2. Tap **Social** in the bottom navigation.
3. Tap **Set up workspace**.
4. Enter a workspace and brand name. Example: `Example Company GTM` / `Example Company`.
5. Add a channel account:
   - Platform: **LinkedIn**
   - Account type: **Company Page**
   - Data mode: **Manual capture** unless an approved read-only connector is available.
6. Add the growth objective:
   - Current followers (baseline)
   - Target followers
   - Target date
   - Secondary outcome: e.g., impressions, qualified interactions, or LinkedIn-sourced qualified inbound.
7. Choose measurement checkpoints. A practical starting point is **24 hours** and **7 days** after publication. Add 1 hour only if your team can reliably capture it.
8. Set the working cadence: posts per week, likely publish windows, content owner, and reviewer.
9. Choose optional SOD/EOD report times. Fabric asks for explicit confirmation before creating any recurring schedule.

### What the first forecast means

After you supply a baseline and date, Fabric can show the pace required to reach the target. It is not a prediction. A more meaningful trend forecast needs a real, comparable history of captured results.

If the app says **Forecast incomplete**, it means it needs a baseline, target date, enough historical data, or a clearer metric definition—not that the program is failing.

---

## 2. Read the Social “Today” screen

Open **Social → Today** at the start of the day. Read it from top to bottom:

### Today’s decision

This is the one action Fabric believes matters most now. Examples:

- “Approve the warehouse-exception post before the 11:30 publishing window.”
- “Capture the 24-hour metrics for the verified July 23 post.”
- “Choose one of three distinct proof pillars for next week.”

### Needs attention

These need a human action. They are deliberately separate from ordinary drafts:

- review requested;
- approved post awaiting manual publish;
- post recorded as published but needing a URL/proof;
- metric window due;
- agent research needing clarification; or
- a report blocked by missing data.

### Growth pulse

The scorecard shows company-page metrics and data quality together.

- **Verified** means Fabric has accepted the source evidence.
- **Entered** means a person supplied the number manually.
- **Partial** means only some fields or checkpoints are available.
- **Unavailable** means the source cannot provide the value.
- **Stale** means the last capture is older than your workspace rule.
- **—** means unknown/not captured.
- **0** means the source explicitly reported zero.

Do not compare a partial day to a fully measured day as if they were equivalent.

---

## 3. Create a company LinkedIn post

1. In **Social → Content**, tap **New content**.
2. Select:
   - company page lane (not founder lane);
   - objective/campaign;
   - intended post window;
   - topic/proof pillar;
   - desired outcome: reach, conversation, clicks, proof, recruiting, etc.
3. Add your brief in plain language. Strong briefs include a real observation, customer/operator context, proof you can stand behind, and any claims the agent must avoid.
4. Attach available source links, photos, product evidence, or prior posts. If attachment support is unavailable on your gateway, add the source URL/note and the app will say that clearly.
5. Ask Fabric to research, outline, or draft. The assistant may use specialized roles such as market scout, voice guardian, copy editor, and measurement steward.
6. Pick one angle. If you reject an angle, say why. Fabric should change the proof pillar rather than endlessly rewording the same post.
7. Review the draft in **Content detail**:
   - claims and linked sources;
   - company voice;
   - repetition/similarity warning against prior approved posts;
   - CTA and formatting;
   - asset and alt text;
   - estimated effort; and
   - any data/claim uncertainty.

### About the LinkedIn preview

Fabric can show line breaks and a mobile-oriented approximation of a LinkedIn post. It cannot guarantee where LinkedIn places “Show more,” how the feed ranks a post, or which audience receives it. Treat the preview as an editing check, not a performance forecast.

---

## 4. Approve and publish safely

### Approve the post

When the exact draft is ready, the authorized reviewer taps **Approve for manual publish**.

That state means:

- this specific version is approved internally;
- it is ready to copy and post manually; and
- it is **not live yet**.

### Publish manually

1. In the approved content item, tap **Copy post**.
2. Tap **Open LinkedIn** if available, or open LinkedIn yourself.
3. Paste, make any final human edits, and publish through LinkedIn.
4. Return to Fabric Social immediately.
5. Tap **I posted this** and paste the exact LinkedIn post URL.
6. Confirm the timestamp if you know it.

Fabric labels the content **Posted — not yet verified** until it has an accepted URL or other proof. This protects reports from counting a copied/approved/scheduled draft as a live post.

### Verify the post

Open the item and confirm the URL/evidence. Once accepted, Fabric changes the state to **Publication verified**. Only then will it count toward live-post cadence and schedule metric checkpoints.

If you cannot obtain a post URL, attach a platform screenshot when supported and identify it as corroborating evidence. Fabric should retain the fact that this is screenshot-based rather than URL/API-based proof.

---

## 5. Capture analytics without inventing numbers

When Fabric says **24h metrics due** or **7d metrics due**:

1. Open the exact content item.
2. Tap **Capture metrics**.
3. Choose the source you actually have:
   - enter values manually from LinkedIn;
   - confirm a screenshot extraction; or
   - import an approved CSV/export if that capability is enabled.
4. Enter only what you can verify. Leave an unavailable number blank.
5. Add a source note if useful: e.g., “LinkedIn post analytics, captured manually at 10:14 BST.”
6. Save.

Record whatever applies to your page/post: impressions, reach, reactions, comments, reposts, saves, clicks, profile views, follower change, website sessions, inbound leads, meetings, and pipeline.

### Important metric rules

- Do not enter `0` just because you do not know a value.
- Do not record page followers as a post-level result unless the source supports that association.
- Do not label a message or inquiry “LinkedIn-sourced” without your agreed UTM/CRM/source rule.
- If a visual took substantial effort, add the effort band or production note. This lets the weekly review compare effort to outcome without assuming expensive media is better.

---

## 6. Use SOD and EOD reports

### Start of day

The SOD brief answers:

- What changed since yesterday/last week?
- What data is missing?
- What needs my approval or proof?
- What should we do today?
- What is the expected result—and how confident is that expectation?

Choose the primary action, then open its content item or metric task.

### End of day

The EOD brief distinguishes:

- **Verified live posts** — accepted post evidence exists.
- **Posted, unverified** — a human says it is live, but proof is missing.
- **Approved for manual publish** — ready, but not live.
- **Draft/research** — production activity, not marketing results.
- **Measured/partial/unavailable metrics** — performance evidence and coverage.

Use the brief to decide the next day’s action. If it says **Data incomplete**, resolve that before declaring a strategy winner or loser.

### Weekly review

Use the weekly report to compare actual cohorts, not one-off anecdotes:

- topic/proof pillar;
- company vs founder lane;
- text vs visual-supported format;
- publish time/window;
- effort band;
- content goal; and
- distribution activity.

The report should show sample size. A single post is a signal to investigate, not proof of a repeatable rule.

---

## 7. Export the evidence ledger

From **Social → Reports**, choose **Export CSV** when enabled.

The export provides normalized tables such as:

- `content_items.csv`
- `publication_evidence.csv`
- `metric_snapshots.csv`
- `daily_scorecard.csv`
- `experiments.csv`
- `reports.csv`

Empty cells mean **not captured/unavailable**, not zero. Keep the accompanying export README with the CSV so future analysis understands that difference.

---

## 8. Set up the agent ensemble responsibly

Fabric can help run a small virtual social team. Give each role enough context:

- **Social Growth Lead:** target, capacity, current scorecard, priorities.
- **Market/Competitor Scout:** approved public watchlist and research boundaries.
- **Audience Researcher:** ICP, pains, exact words customers use, proof sources.
- **Voice Guardian:** what makes your company voice distinct and what feels like AI slop.
- **Content Strategist:** proof pillars, campaign goals, and rejected angles.
- **Copy Editor:** selected angle, CTA, formatting preference.
- **Visual Direction:** real product/customer proof and design constraints.
- **Measurement Steward:** required checkpoints, data source, and null/zero rules.
- **Report Analyst:** executive brief format and business attribution definitions.

An agent output is a suggestion until a human reviews it. Do not ask the agent to claim it posted, saw private analytics, or verified a customer fact unless you supplied the evidence or a real connector reports it.

---

## 9. Common states and what to do

| What you see | What it means | What to do |
| --- | --- | --- |
| Social unavailable | Your gateway has not advertised the secure Social capability | Update/connect to a compatible gateway; do not expect a local fake workspace |
| Forecast incomplete | Baseline/date/history/metric definition is missing | Complete setup or capture more comparable data |
| Posted — not verified | Publication was recorded but no accepted proof exists | Paste the exact post URL or attach/confirm evidence |
| Metrics partial | Some checkpoint fields are missing | Capture what is available; mark truly unavailable fields honestly |
| Data stale | Last metric capture is old | Refresh/capture a new snapshot before making a decision |
| Outcome unknown | A save/approval suffered an ambiguous connection result | Refresh the item; do not submit a second different action |
| Connector unavailable | LinkedIn/API permissions are not available | Use manual capture; do not enter credentials into chat |
| Needs clarification | The agent lacks a decision that affects the work | Answer it from the content item so the decision is recorded |

---

## Daily five-minute routine

1. Open **Social → Today**.
2. Resolve any missing proof or due analytics first.
3. Pick the single highest-value action.
4. Review/approve one item or capture one measurement checkpoint.
5. At end of day, read the EOD brief and confirm tomorrow’s action.

Consistency and evidence quality come before volume. The goal is not to make the feed noisier; it is to learn which credible company stories generate attention and demand for your specific audience.
