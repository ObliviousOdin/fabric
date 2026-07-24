# Fabric Social — Mobile Operator Guide

**Audience:** GTM leads, founders, and content operators
**First workflow:** LinkedIn company-page drafting with human-only publication

## Read this first: what is available today

Fabric already provides **Social Studio** Compose/Library flows on its supported clients:

```text
Choose a social brief → start a Fabric session → review the caption → copy it → publish manually outside Fabric
```

Social Studio does not currently post to LinkedIn, schedule a post, fetch LinkedIn analytics, or maintain a durable publishing record. A copied caption is not proof that anything went live.

The next proposed stage is a responsive **Social Growth dashboard plugin**. It is intended to run in a phone browser through the authenticated Fabric dashboard, not as a claimed native-app or mobile-PWA tab. It adds a profile-scoped operating ledger for goals, draft review, manual evidence, and reports.

## What the product does not do

It does not:

- publish, schedule, comment, react, follow, invite, or reshare on LinkedIn;
- request LinkedIn passwords, cookies, or API tokens;
- turn a copied caption into a “published” result;
- claim platform analytics it did not receive from you; or
- guarantee distribution, “Show more” behavior, engagement, followers, or inbound pipeline.

## Before you begin

Have these ready:

- current company-page follower count and a target date;
- the metric definitions that matter besides followers: impressions, qualified comments, clicks, qualified inbound, meetings, and so on;
- company/founder lane boundaries, proof rules, and prohibited claims;
- the reviewer, manual publisher, reply owner, and report owner;
- a real operating observation, approved source, customer-safe proof, or explicitly labeled opinion for the draft;
- a method for capturing the post URL and metrics after manual publication; and
- a time zone and preferred daily-review cadence.

You may begin with partial context. The product should show incomplete forecasts and unavailable metrics honestly rather than inventing answers.

---

## 1. Draft a post in Social Studio

1. Open Social Studio from the current Fabric client.
2. Choose the LinkedIn drafting flow and provide a focused brief:
   - lane: company page or founder;
   - audience and one intended takeaway;
   - the evidence/observation that supports the claim;
   - any claim, legal, privacy, or voice constraints.
3. Let Fabric create the drafting session.
4. Read the output as a suggestion, not a fact. Check that it is specific, sourced, and sounds like the intended lane.
5. Use **Copy caption** only after a human has reviewed it.

### How to avoid AI-slop

A useful draft begins with something real: a firsthand operating observation, an approved product fact, a customer-approved proof point, or a clearly marked opinion. Ask for no more than two or three materially different angles. If no evidence exists, choose **Hold** or gather an observation instead of filling the calendar.

Keep company and founder voices separate. A company post can lead with product evidence; a founder post should earn its point of view from firsthand experience. Do not repackage a rejected pillar into near-duplicate rewrites.

---

## 2. Hand the draft to a human publisher

When a caption is ready:

1. Confirm the lane, account, final text, asset/privacy checklist, CTA, and reply owner.
2. Copy the caption from Fabric.
3. Open LinkedIn yourself and paste/edit/publish there.
4. Keep final edits human-visible. If the caption changes materially, return to the ledger and request another review rather than treating the original approval as unchanged.
5. Plan a real reply-monitoring window. Fabric must not generate artificial engagement or post comments for you.

Use clear language:

- **Approved for manual copy** means a human approved this exact caption for copying.
- It does **not** mean Fabric scheduled or published it.

---

## 3. Use the proposed Social Growth dashboard on a phone

Once the `social-gtm` dashboard plugin is installed and enabled, open the authenticated Fabric dashboard in a mobile browser. The initial dashboard has four compact areas.

### Today

Read only the decision-relevant items:

- one recommended action, which may be **Hold today**;
- open reviews or a changed draft requiring re-approval;
- missing post URL or metric observations;
- a data-health label explaining whether an item is user-supplied, partial, stale, unavailable, or complete; and
- the named owner and next deadline.

A no-data screen means no data is known. It never means zero reach or zero engagement.

### Drafts

Create a ledger entry by attaching the exact caption snapshot to its source Fabric session. The dashboard records a caption hash and version.

A reviewer chooses one of:

- **Request changes** — explain what is unsafe, unsupported, repetitive, or off-voice.
- **Approve for manual copy** — approves that exact version only.
- **Hold** — deliberately do not publish now.

Any caption change invalidates the prior approval.

### Evidence

After a human publishes externally, record what you personally know:

1. Select the approved draft.
2. Choose **Record user-reported post URL**.
3. Paste the exact LinkedIn URL, add the human’s attestation time, and save.
4. The dashboard labels this as **user-reported**. It does not claim API verification.

If the post was not published, mark it **Held/not posted** with a short reason. This is useful information, not a failure.

### Reports

Enter metric observations only when you can state their source and time window. For each value, record:

- metric name and value;
- observation date/window;
- capture date;
- source: user-entered in MVP;
- coverage: complete, partial, unavailable, or stale; and
- a correction/supersession note if you replace a prior entry.

The dashboard’s EOD report should answer:

1. What human work was completed?
2. What was copied, held, or user-reported as posted?
3. Which values are known, unknown, partial, stale, or user-supplied?
4. What changed from the selected comparison window?
5. What is the next decision, owner, and due date?

Export CSV when you need the underlying rows for a review. Empty numeric cells mean no observed value; they are not zeros.

---

## 4. Practical LinkedIn execution guidance

Fabric can help inspect a caption, but LinkedIn controls its own display and distribution. Use the copy review to check:

- a concrete opening rather than a generic AI claim;
- short, readable paragraphs and intentional line breaks;
- one clear point of view and one credible example;
- a CTA appropriate to the post’s objective;
- accurate links/UTMs if your team has adopted them;
- alt text and privacy checks for any asset you add manually; and
- a reply owner who can answer genuine questions.

The product may display an approximate text preview. It cannot promise a “Show more” cut, reach, or performance outcome.

## 5. Data, connection, and permission states

### Honest data labels

| Label | Meaning |
| --- | --- |
| `0` | The supplied source explicitly reported zero |
| `Not captured` | No value has been observed |
| `Partial` | Some requested fields or checkpoints are known |
| `Unavailable` | The source cannot provide the value |
| `Stale` | The last observation is older than the team’s freshness rule |
| `User-supplied` | A human entered or attested the value; it is not platform-API verified |

### If something is unavailable

- **No source session:** link the draft manually or leave the session reference absent; do not fabricate one.
- **No metrics:** record the reason as unavailable; do not enter zero.
- **Dashboard authentication failed:** reconnect to the dashboard. Do not treat the empty/error state as an empty social history.
- **Offline:** do not assume a save completed. Refresh and reconcile before re-entering a review, URL, or metric observation.
- **A draft overlaps another lane:** hold it, change the proof pillar, or document why proceeding is intentional.

## 6. Roles and human boundaries

| Role | May do | Must not do |
| --- | --- | --- |
| Contributor | capture evidence, start a draft, request review | claim a draft is live |
| Reviewer | approve the exact caption for manual copy, request changes, hold | approve a changed caption silently |
| Publisher | manually post outside Fabric, record an attestation/URL | imply Fabric posted it |
| Report owner | enter source-labeled observations and export reports | convert unknown data to zero |
| Social assistant/cron | research, draft, summarize, flag gaps | publish, schedule, comment, or invent analytics |

## 7. Daily operating loop

```text
Read Today → choose publish/prepare/reply/measure/hold →
start or review a source-backed draft → human manual copy/publish →
record user-supplied evidence → record available metrics →
read the EOD decision brief → learn and repeat
```

The highest-quality outcome may be **do not publish today**. The system succeeds when it makes that decision clear, protects the company voice, and preserves the truth about what happened.