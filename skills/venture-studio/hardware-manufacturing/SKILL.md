---
name: hardware-manufacturing
description: "Move hardware from CAD to mass production — mechanical design, PCB schematic, layout and DFM review, prototyping, EVT/DVT/PVT builds, factory selection, quality control, certification, and logistics. Use when the user asks about manufacturing a physical product, PCBs, tooling, or production runs."
version: 1.0.0
author: Fabric
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [manufacturing, cad, pcb, dfm, evt-dvt-pvt, production]
    related_skills: [d2c-smart-products]
---

# Hardware Manufacturing

Use this skill when the user needs to take a physical product from an idea or CAD file to repeatable mass production: enclosure design, PCB design and fabrication, prototype iteration, EVT/DVT/PVT builds, factory selection, quality plans, certification, and freight. You cannot mill aluminum from a terminal, but you can do most of the leverage work: interrogate requirements, run design-rule checks, audit BOMs against live distributor stock, draft RFQ packages, compute tooling break-evens, and write the gate checklists that keep a build honest.

Do NOT use this skill for firmware or app work on the device (ordinary software workflow), for go-to-market, channel, and subscription questions on a connected product (load `d2c-smart-products` with skill_view), or for a quick "is this sensor even viable" feasibility hack — that is a spike, not a production program.

## Workflow

1. **Scope the program.** Ask the user before designing anything: target retail price and unit-cost ceiling, lifetime and first-year volume, launch markets (drives certification), power source (mains, battery, USB), environment (indoor/outdoor, IP rating), and hard deadline. Write the answers into a one-page product requirements doc in the repo — every later trade-off resolves against it.
2. **Design mechanical for the real process.** Pick the production process from the volume table below *first*, then CAD to its constraints. A part designed for 3D printing and later "converted" to injection molding is a redesign, not a conversion.
3. **Design the electronics.** Schematic capture, then layout, then run ERC/DRC, then a DFM pass against the chosen fab's published capabilities. Lock the BOM with availability checks before layout is final.
4. **Prototype in tight loops.** Order boards and printed enclosures in small batches; bring up, test, log defects, revise. Each loop should answer named questions, not just "see how it looks."
5. **Run the stage gates.** EVT proves the design works, DVT proves it survives, PVT proves the factory can build it. Do not skip gates to save calendar time — each gate exists because the next phase is more expensive to fix things in.
6. **Select the factory and cut tools.** RFQ at least three suppliers, audit the winner, sign off golden samples, and only then release tooling payment milestones.
7. **Certify.** Engage an accredited test lab during EVT for pre-scans; formal FCC/CE/UL testing runs on DVT units, and certificates must exist before PVT units ship to customers.
8. **Package and ship.** Design packaging that survives ISTA drop testing, pick Incoterms deliberately, and decide air vs. ocean per shipment based on margin and urgency.

## Mechanical CAD phase

| Tool | Best when | Notes for the agent |
|---|---|---|
| Fusion 360 | Startup default; parametric solids plus built-in CAM and simulation | Free for personal/non-commercial use only — verify current Autodesk licensing before recommending for a business; closed format, export STEP for portability |
| Onshape | Team collaboration, browser-only environments | Free plan makes documents public; version control is built in |
| FreeCAD | Open source, scriptable, headless-friendly | You can drive it from Python for batch STEP/STL export and geometry checks |
| CadQuery / build123d | Code-defined parametric parts | Fully agent-operable: generate, mutate, and export models in a script |

Design to the process you will actually ship on, chosen by lifetime volume:

| Volume (units) | Process | Piece price | Up-front cost | Design constraints to respect |
|---|---|---|---|---|
| 1–50 | 3D print (FDM/SLA/MJF) | High | ~none | Orientation, overhangs, layer strength anisotropy |
| 50–500 | CNC machining | Medium-high | Fixturing only | Internal corner radii, tool access, stock sizes |
| 100–1,000 | Urethane casting | Medium | Soft silicone tool, low thousands | Tool life ~20–25 shots; near-molding geometry |
| 1,000+ | Injection molding | Low (often under a dollar) | Tooling: low tens of thousands typical | Draft angles, uniform walls, ribs not slabs, avoid undercuts |

Injection-molding rules that save redesigns: 1–2 degrees of draft on every face parallel to pull direction; keep walls uniform (thick sections sink and warp); use ribs at 50–60% of wall thickness for stiffness; every undercut adds a side action and real money to the tool; put the parting line and ejector marks where cosmetics allow. Get a DFM review from the molder before the tool is cut — reputable shops provide it free with a quote.

## PCB phase

Default to KiCad unless the user has an existing toolchain. It is free, has no seat limits for contractors, and `kicad-cli` lets you run ERC, DRC, and gerber/BOM export from the terminal — meaning you can verify a design without opening a GUI:

```
kicad-cli sch erc project.kicad_sch
kicad-cli pcb drc project.kicad_pcb
kicad-cli pcb export gerbers project.kicad_pcb -o fab/
```

Sequence: schematic capture → ERC clean → footprint assignment → layout → DRC clean against the *fab's* rule set (import their trace/space, drill, and annular-ring limits; do not trust defaults) → DFM review → panelize if the assembly house wants arrays (add rails, fiducials, and mouse bites or v-scores per their spec).

**Fab and assembly.** For prototypes and small runs, turnkey fab+assembly houses (JLCPCB, PCBWay, Seeed, Aisler, or a domestic quick-turn shop for schedule-critical spins) are cheaper than splitting fab and assembly. For production, keep assembly close to the enclosure factory to shorten the box-build chain.

**BOM management.** Before layout is final, check every line item on a parts aggregator (Octopart or distributor APIs) for: live stock at two or more distributors, lifecycle status (reject EOL and NRND parts for new designs), and price breaks at your target volume. Nominate a second source for every critical IC or note it as single-source risk in the gate checklist. Store the BOM as CSV in the repo with columns for MPN, second-source MPN, reference designators, and per-unit cost at target volume — you can then re-audit availability with a script on every build.

## Prototype iteration loop

Run each spin as a small, named experiment rather than a vibes-based reorder:

1. **State the questions.** Before ordering, list what this revision must answer (e.g. "does the antenna meet range spec inside the enclosure", "does the snap fit survive 50 cycles"). If a spin answers nothing new, skip it.
2. **Order small.** 5–10 boards assembled, 2–3 enclosures printed. Speed beats quantity until DVT.
3. **Bring up methodically.** Power rails first with current limiting, then clocks, then peripherals. Log every deviation in a bring-up notes file in the repo, keyed to board serial number.
4. **Disposition every defect.** Each issue gets a root cause and one of: fix in next rev, tolerate with rationale, or needs-more-data. Track them in a defects table per revision.
5. **Bump the revision everywhere at once.** Board silkscreen, CAD file names, BOM, and the release folder all move together; mixed-revision confusion at the factory is expensive and entirely self-inflicted.

Three to four board spins before EVT is normal for a product with a radio; budget calendar time for it rather than pretending rev A will be final.

## Stage gates: EVT / DVT / PVT

| Gate | Builds what | Typical qty | Proves | Exit criteria |
|---|---|---|---|---|
| EVT (Engineering Validation) | Works-like units, often prototype processes | 20–100 | The design functions | All features demoed; major bugs dispositioned; BOM risks listed; pre-scan EMC results reviewed |
| DVT (Design Validation) | Looks-like/works-like units on production tooling | 50–500 | The design survives | Reliability, drop, thermal, and battery tests passed; certification testing complete or in flight; cosmetic spec signed |
| PVT (Production Validation) | Sellable units on the production line at rate | 500+ or 5–10% of first order | The factory can build it | Line yield at target (typically >95%); cycle time measured; QC plan executed; units are sellable |

Treat exit criteria as blocking. A "conditional pass" with an untracked list of exceptions is how programs slip a quarter. Record every waiver with an owner and a close-by date.

## Tooling cost and MOQ math

Amortize tooling into unit economics before committing:

```
effective unit cost = piece price + (tooling cost / expected lifetime volume)
```

Worked example: a $30,000 steel mold over 10,000 units adds $3.00/unit to a $1.20 molded part ($4.20 effective). The same part CNC'd at $18 needs no tooling. Break-even is tooling ÷ (CNC price − piece price) = 30,000 ÷ 16.80 ≈ 1,786 units — above that, cut the tool. Aluminum "soft" tools cost a third to a half as much but are typically good for 10k–100k shots; hardened steel multi-cavity tools cost multiples more and run to the millions. Factory MOQs work the same way: a stated MOQ is usually a price point, not a wall — ask for the price at MOQ, at half, and at 2x, and negotiate from the curve.

## Factory selection and communication

Shortlist 3–5 candidates (sourcing platforms, referrals, or the fab house's assembly partners). Send each an identical RFQ package: STEP files, 2D drawings with tolerances and critical dimensions flagged, gerbers and centroid files, BOM, cosmetic spec, target volumes, and required certifications. Compare quotes line by line — a low headline price with vague tooling terms is worse than a clear expensive one.

Before mass production: audit the factory (in person or via a third-party audit firm), agree on a **golden sample** — a signed-off reference unit both sides keep — and write a QC plan covering incoming material inspection, in-process checks, and final inspection. Use AQL sampling (general inspection level II is the norm) with typical thresholds of 0 for critical defects, 1.0–2.5 for major, 4.0 for minor. Book third-party pre-shipment inspection for at least the first three shipments; it costs a few hundred dollars and catches container-level disasters.

## Certification pass

- **FCC (US):** every electronic product needs unintentional-radiator testing; anything with a radio needs intentional-radiator certification. Using a pre-certified radio module with its modular approval intact dramatically shrinks scope — do not route antennas differently than the module's grant allows.
- **CE (EU):** mostly self-declaration against harmonized standards (EMC Directive, LVD if mains-powered, RED if it has a radio); keep a technical file. UKCA parallels CE for Britain.
- **UL/ETL (safety):** not legally mandatory in the US but required by most retailers and insurers for mains-powered products. Batteries need UN 38.3 to ship lithium cells at all, and often IEC 62133.
- Engage an accredited test lab at EVT for informal pre-scans (a day of chamber time finds EMC problems while the board can still change); run formal testing on DVT hardware; budget several weeks and five figures for a wireless consumer product across US+EU.

## Packaging and logistics

Design the retail box, inserts, and master carton together; validate with ISTA 3A (parcel) or 1A drop testing at DVT. Print unit and carton barcodes the 3PL can scan. On shipping terms, know the Incoterm you sign:

| Incoterm | Seller responsibility ends | Use when |
|---|---|---|
| EXW | At the factory door | You have your own freight forwarder and want control |
| FOB | Loaded on vessel at origin port | The common default; you own ocean freight and import |
| DDP | Delivered, duties paid, at your door | You want zero logistics work and accept the markup |

Air freight costs roughly 4–8x ocean per kg but arrives in days, not 4–6 weeks port-to-port plus customs. Standard play: air the first small batch to hit launch, ocean the rest. Duties, tariffs, and customs brokerage belong in landed cost from day one — compute landed cost per unit, not factory cost.

## Build-readiness checklist template

Draft one of these in the repo before each gate and review it with the user; the gate is passed when every box is checked or waived with an owner.

```markdown
# [Product] — [EVT|DVT|PVT] Build Readiness — [date]

## Design
- [ ] CAD frozen at rev ___; STEP + drawings exported to /releases/[rev]/
- [ ] Schematic/layout frozen; ERC and DRC clean (attach reports)
- [ ] Open issues from previous build dispositioned (list waivers below)

## Supply
- [ ] BOM availability re-checked within 7 days; no EOL/NRND lines
- [ ] Long-lead parts (>8 weeks) ordered or in stock at CM
- [ ] Single-source risks listed with mitigation

## Build
- [ ] Quantity ___ agreed; PO issued; build dates confirmed
- [ ] Test plan written: what each unit must pass before it counts
- [ ] Fixtures/test jigs ready (DVT+); golden sample signed (PVT)

## Compliance & downstream
- [ ] Cert status: pre-scan / formal testing / certificates on file
- [ ] Packaging rev ___ ready (DVT+); ISTA drop test passed (PVT)
- [ ] QC plan + AQL levels agreed with factory (PVT)

## Waivers
| Item | Risk | Owner | Close by |
|---|---|---|---|
```

## Common failure modes

- **Designing for the prototype process.** A beautiful 3D-printed enclosure with zero draft, undercuts everywhere, and 4 mm walls is not "almost ready for molding." Pick the production process in step 2 and CAD to it from the start.
- **Freezing layout before the BOM is buyable.** A single out-of-stock IC with a 40-week lead time stalls the whole program. Audit availability before layout is final and again before every build.
- **Skipping EVT because "the prototype already works."** One working bench unit proves nothing about twenty; EVT exists to find the failures that only show up in a population.
- **Treating MOQ as a wall instead of a price curve.** Ask for quotes at multiple volumes; almost everything is negotiable against the amortization math.
- **No golden sample.** Without a signed reference unit, every cosmetic dispute with the factory becomes your word against theirs — and you lose, because they already built the units.
- **Certifying after tooling.** An EMC failure found at PVT means board respins against a frozen enclosure. Pre-scan at EVT while everything can still move.
- **Quoting factory cost as unit cost.** Landed cost includes tooling amortization, freight, duty, inspection, and yield loss. Products die on the difference.
- **Answering channel and pricing questions from here.** Retail strategy, subscriptions, and D2C funnels for a connected product belong to `d2c-smart-products` — load it with skill_view rather than improvising.
