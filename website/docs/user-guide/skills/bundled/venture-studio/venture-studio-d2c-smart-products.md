---
title: "D2C Smart Products"
sidebar_label: "D2C Smart Products"
description: "Take a direct-to-consumer smart product from concept to customers — hardware, firmware, app, and cloud architecture, connectivity choices (BLE, Wi-Fi, Thread..."
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# D2C Smart Products

Take a direct-to-consumer smart product from concept to customers — hardware, firmware, app, and cloud architecture, connectivity choices (BLE, Wi-Fi, Thread/Matter), compliance, packaging, and a D2C storefront launch. Use when the user wants to build a connected consumer device or IoT product end to end.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/venture-studio/d2c-smart-products` |
| Version | `1.0.0` |
| Author | Fabric |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `iot`, `d2c`, `smart-products`, `firmware`, `connectivity`, `ecommerce` |
| Related skills | [`hardware-manufacturing`](/user-guide/skills/bundled/venture-studio/venture-studio-hardware-manufacturing), [`build-something-people-want`](/user-guide/skills/bundled/venture-studio/venture-studio-build-something-people-want), [`shopify`](/user-guide/skills/optional/productivity/productivity-shopify) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Fabric loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# D2C Smart Products

Use this skill when the user wants to take a connected consumer device from idea to paying customers — a smart lamp, air-quality monitor, pet feeder, garden sensor, wearable — treating hardware, firmware, companion app, cloud, and the direct-to-consumer storefront as one coherent build. This is the front door for the whole journey; it makes the cross-stack decisions and routes specialist depth to sibling skills.

Do NOT use this skill for: deep manufacturing questions (DFM, tooling, EVT/DVT/PVT, factory selection, QC plans) — load `hardware-manufacturing` with skill_view; deciding whether the product deserves to exist at all — load `build-something-people-want` with skill_view first and come back with a validated concept; or a storefront with no device attached — install the optional `shopify` skill (`fabric skills install official/productivity/shopify`) and load it directly.

## The four-stack reality

Every connected product ships four coupled systems. A decision in any one constrains the other three, so name the couplings before writing a line of firmware:

| Stack | You are shipping | What it forces on the others |
|---|---|---|
| Device (hardware + firmware) | PCB, radio, sensors, enclosure, bootloader | Radio choice dictates pairing UX and cloud ingest path; flash size caps OTA image size |
| Companion app (mobile/web) | Pairing, control, notifications | A BLE-only device uses the phone as its gateway — cloud sync only happens while the app runs |
| Cloud backend | Device registry, telemetry, OTA service, auth | Per-device credentials must be injected at manufacture, which becomes a factory-line step |
| Commerce + fulfillment | Storefront, packaging, logistics, support | Landed cost sets the BOM ceiling; return rate tracks pairing-flow quality almost 1:1 |

When the user proposes a change in one stack, state the ripple in the other three out loud before agreeing to it.

## Workflow

1. **Frame the product.** Ask the user: what does the device sense or actuate, where does it live (mains power or battery?), who pairs it (owner's phone? household?), what must work when the internet is down, and target retail price. If the concept itself is unvalidated, pause and load `build-something-people-want` with skill_view.
2. **Pick connectivity** using the decision table below. This is the highest-leverage decision in the project — it fixes power budget, pairing UX, cloud protocol, and certification scope simultaneously. Write the choice and its rejected alternatives into the architecture brief.
3. **Pick the compute platform** (MCU vs Linux SoM table below). Default to the smallest thing that does the job; every step up in compute is a step up in unit cost, idle power, boot time, and patching burden.
4. **Design provisioning and pairing before the schematic is final.** Sketch the out-of-box flow as a numbered script: unbox, power on, open app, discover device, transfer Wi-Fi credentials (BLE-assisted commissioning is the norm), claim ownership, land on a working dashboard. Target under 2 minutes and zero typed serial numbers — use a QR code on the device carrying its identity. Prototype this flow as a clickable mock and walk the user through it.
5. **Build firmware with OTA from day one.** The first image flashed at the factory must already know how to update itself: A/B partition slots (or bootloader + recovery), signed images verified before boot, automatic rollback on failed health check, staged rollout percentages controlled server-side. Retrofitting OTA after launch is how fleets die.
6. **Keep the cloud minimal.** Version one needs exactly three services: a device registry (identity, ownership, claim/unclaim), a telemetry ingest path (MQTT or HTTPS into a queue, then a time-series store), and an OTA service (signed artifact storage plus rollout targeting). Resist dashboards, rules engines, and ML pipelines until real fleet data demands them. Managed IoT cores are fine at small fleet sizes; keep the device-facing protocol boring (MQTT + TLS) so you can migrate.
7. **Apply the security and privacy baseline** (non-negotiable, and increasingly a legal requirement): unique credentials per device injected at manufacture — never a shared secret or default password; firmware images signed, verified by an immutable bootloader; TLS for every network hop; a published vulnerability-disclosure contact; a stated security-update support period; collect the minimum telemetry and document it in a plain-language privacy note.
8. **Clear regulatory gates early.** See the compliance section — engage a test lab while the PCB is still cheap to change, not after tooling.
9. **Hand manufacturing depth to the specialist.** For DFM review, factory selection, test fixtures, and build stages, load `hardware-manufacturing` with skill_view. Bring it the architecture brief so it inherits your connectivity and provisioning decisions.
10. **Launch D2C.** Stand up the storefront (install and load the `shopify` skill for API work: `fabric skills install official/productivity/shopify`), price against landed cost, design packaging around the pairing flow, and wire the support loop before the first unit ships.
11. **Close the loop.** Instrument the setup funnel (power-on → paired → first successful action), watch early return reasons, and feed fixes back through OTA. The first 500 units are an extended field test — plan staffing for it.

## Connectivity decision table

| Link | Power draw | Range | Module cost | Pairing UX | Pick when |
|---|---|---|---|---|---|
| BLE | Very low; coin-cell viable | ~10-50 m, phone must be near | Low | Best-in-class: tap-to-pair in app | Device is used with a phone nearby; no always-on cloud need |
| Wi-Fi | High; mains or large battery | Home-wide | Low | Hardest: credential transfer step, router quirks drive support tickets | Mains-powered, needs direct cloud link, video/audio bandwidth |
| Thread / Matter | Low; battery viable | Mesh, home-wide via border router | Moderate | Good and improving: standardized commissioning via QR code | Smart-home category product that must interoperate with the major ecosystems |
| Cellular (LTE-M / NB-IoT) | Moderate; needs real battery | Anywhere with coverage | High, plus recurring SIM cost | Zero-config: works out of the box | Device leaves the home (trackers, vehicles, agriculture) |
| LoRa / LoRaWAN | Very low | km-scale, low bandwidth | Low-moderate | Gateway required; not consumer-friendly alone | Sparse sensor data over long range; usually paired with a hub you also ship |

Hybrids are common and often right: BLE for commissioning plus Wi-Fi for steady-state is the default consumer pattern. If the product is in the smart-home category, evaluate Matter seriously — retail buyers and ecosystem badges increasingly expect it — but verify current certification cost and timeline before committing.

## Compute platform

| Dimension | ESP32-class MCU | Linux SoM |
|---|---|---|
| Unit cost | Single-digit dollars | Tens of dollars and up |
| Idle power | Microamp deep sleep | Hundreds of milliwatts |
| Boot time | Milliseconds | Seconds |
| OTA model | Whole signed image, A/B slots | Full rootfs or containerized (RAUC/Mender-style dual slot) |
| Security surface | Small; secure boot + flash encryption on-chip | Entire OS to patch for the product's support life |
| Choose when | One job, battery or cost sensitive, radio built in | Camera, voice, local ML, display, or complex protocol stacks |

Default to the MCU. A Linux SoM is justified by workload, never by developer comfort — you are signing up to patch an operating system for the stated support period of every unit sold.

## Deliverable: product architecture brief

Draft this early, keep it current, and hand it to every sibling skill. Save it in the project repo.

```markdown
# [Product] Architecture Brief

## Product frame
- What it senses/actuates: 
- Power source: mains | battery (target life: )
- Offline behavior (what still works with no internet): 
- Target retail price: $   | Landed cost ceiling: $

## Connectivity
- Primary link:            | Commissioning path: 
- Rejected alternatives and why: 

## Compute + firmware
- Platform:                | OTA scheme: A/B slots, signed, staged rollout
- Update support period promised to customers: 

## Cloud (v1 = three services only)
- Registry:  | Telemetry ingest:  | OTA service: 

## Security & privacy baseline
- Per-device credentials injected at:        (factory step owner: )
- Firmware signing key custody: 
- Data collected and why (plain language): 

## Compliance targets (verify per market with a test lab)
- Markets:      | Radio module pre-certified: yes/no
- Lab engaged:  | Budget/timeline: 

## Launch
- Storefront:   | Battery shipping constraints: 
- Setup-funnel metric owner:   | Support/RMA flow: 
```

## Compliance overview (awareness, not legal advice)

- **US:** FCC authorization for the radio and unintentional-emissions testing for the whole product. Using a pre-certified radio module with modular approval shrinks the radio work but does not eliminate end-product testing.
- **EU:** CE marking spans several directives — radio equipment, EMC, safety, RoHS — and radio-equipment cybersecurity requirements now apply to consumer connectables (no default passwords, update capability). The UK mirrors this with UKCA plus its own consumer-connectable security law requiring a stated update period and disclosure policy.
- **Elsewhere:** Canada, Japan, and Australia each have their own radio regimes. Certify for launch markets only; add markets later.
- **Batteries:** lithium cells trigger transport testing and shipping-mode requirements (ship-mode firmware that keeps the device dark in transit is a real feature).

Budget real money (five figures) and 8-16 weeks for a first certification round. Rules tighten yearly — verify current requirements per market with an accredited test lab before locking the schedule; do not certify from memory or from this document.

## D2C launch economics

Landed cost = BOM + assembly + test + packaging + inbound freight + duty + certification amortization + warranty reserve. As a starting rule, retail price should be at least 3-4x landed cost — the gap funds acquisition, returns, support, and the next production run. If the math only works at 2x, the product needs a BOM diet, a higher price, or an honest recurring-revenue layer (consumables or a service tier that delivers real ongoing value — not a paywalled basic feature, which earns review-score destruction).

Packaging is part of the pairing flow: the QR code, the first thing visible on opening, and the quick-start card should walk the same numbered script as step 4 of the workflow. Unboxing is a UX surface with a return-rate attached.

For the storefront itself — catalog, checkout, pre-orders vs in-stock, shipping rules for battery products — install the optional `shopify` skill with `fabric skills install official/productivity/shopify`, then load `shopify` with skill_view for the API-level work.

## Support loop and fleet health

Wire these before the first unit ships, not after the first angry email:

- **Setup funnel telemetry.** Emit anonymous events for power-on, discovery, credential transfer, claim, and first successful action. The drop-off between any two steps is your top engineering priority for the next firmware release.
- **In-app diagnostics.** A "get help" screen that captures signal strength, firmware version, and last error, and can attach it to a support ticket. Cuts median resolution time dramatically and turns vague tickets into bug reports.
- **A real RMA path.** Decide in advance: advance replacement or return-first, who pays return shipping, what happens to returned units (refurb, teardown analysis, scrap). Returned units are your best failure-analysis data — route a sample to engineering, not straight to the recycler.
- **Release cadence.** Commit to a monthly firmware train for the first six months. Staged rollout: 1% for 48 hours, then 10%, then fleet-wide, with automatic halt on a rising health-check failure rate.
- **Review triage.** Storefront and marketplace reviews are unfiltered field reports. Tag each one to a stack (device, app, cloud, fulfillment) weekly and trend it — this is the cheapest fleet analytics you will ever get.

## Pre-launch gate

Run this checklist with the user before accepting the first order:

```markdown
## Launch gate — all boxes or no launch
- [ ] OTA verified end-to-end on production hardware: update, corrupt-image reject, rollback
- [ ] Per-device credentials confirmed unique across a sample of the first production batch
- [ ] Pairing flow tested by 5+ people outside the team, on both mobile platforms, median < 2 min
- [ ] Certification paperwork in hand for every launch market
- [ ] Ship-mode verified: device dark in transit, wakes correctly on first power-on
- [ ] Landed cost recomputed from actual invoices; retail price still clears the multiple
- [ ] Storefront test order placed, fulfilled, and refunded end to end
- [ ] Support inbox, diagnostics path, and RMA policy live; someone owns them by name
- [ ] Privacy note and security-update support period published
```

## Common failure modes

- **OTA retrofitted after launch.** The factory image can't update itself, so every fix requires a recall or a truck roll. OTA is a day-one bootloader decision, not a v1.1 feature.
- **Shared device secret.** One key baked into every unit; one teardown compromises the fleet. Unique per-device credentials, injected on the line, with signing keys held off the factory network.
- **Pairing designed last.** The team ships a flawless PCB whose setup flow needs the user to type a 16-character serial into a captive portal. Pairing failures dominate returns and one-star reviews; design the flow before the schematic freezes.
- **Cloud maximalism.** A rules engine, data lake, and three dashboards for a fleet of 40 beta units. Registry, telemetry, OTA — nothing else until fleet data demands it.
- **Compliance discovered at tooling.** An antenna or enclosure change after certification testing restarts the clock and the invoice. Pre-scan at the prototype stage.
- **Pricing from BOM instead of landed cost.** Freight, duty, warranty reserve, and cert amortization silently eat the margin that looked healthy on the BOM spreadsheet.
- **Linux SoM chosen for developer comfort.** Now the product idles at half a watt, boots in eight seconds, and needs OS patches for five years.
- **Phone-as-gateway surprise.** A BLE-only device is sold with cloud features; customers discover sync stops when they leave the house. Either add Wi-Fi/Thread or market it honestly as local-first.
- **Ignoring ship-mode.** Devices arrive with dead batteries or, worse, wake in transit. Firmware ship-mode plus transport-tested cells, from the first sellable batch.

## Hand-offs

- Manufacturing depth (DFM, factories, build stages, QC): load `hardware-manufacturing` with skill_view.
- Concept validation, positioning, early-customer discovery: load `build-something-people-want` with skill_view.
- Storefront build and commerce APIs: `fabric skills install official/productivity/shopify`, then load `shopify` with skill_view.
