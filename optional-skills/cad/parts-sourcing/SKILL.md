---
name: parts-sourcing
description: "Source mechanical parts and hardware — Misumi configurable components and meviy fabrication quotes, McMaster-Carr hardware with CAD downloads, aluminum extrusion systems, and building BOMs with part numbers, prices, and STEP models."
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [Sourcing, Misumi, McMaster, BOM, Hardware, Extrusion, Procurement, Fabrication]
    related_skills: [sheet-metal, code-cad]
---

# Parts Sourcing (Misumi / McMaster / extrusions)

Turn a design into an orderable bill of materials: configured part
numbers, prices, lead times, and STEP models for the CAD assembly.

**Reality check**: neither Misumi nor McMaster-Carr has a general public
ordering API. Sourcing is a browser workflow — use Fabric's browser tools
to configure parts and download CAD, and keep the human in the loop for
accounts, carts, and checkout. Never place orders autonomously.

## Misumi

Misumi's superpower is **configurable part numbers**: dimensions are
encoded in the part number itself, so you can often derive the exact
part number from the design parameters.

- Pattern example (linear shaft): `PSFJ6-200` = 6 mm dia × 200 mm length.
  Each product family's page documents its code grammar (alterations
  appended: `-M4`, `-KC10`, etc.).
- Workflow: browser-navigate the product family page → set dimensions in
  the configurator → capture the generated part number and price/lead
  time → download STEP from the CAD-data link (account required).
- Verify every derived part number against the configurator before
  putting it in a BOM — code grammars differ per family and region
  (misumi-ec.com vs regional sites).

**meviy** (Misumi's fabrication service): upload STEP → instant quotes
for sheet metal, machined plates, and turned parts. Pairs with the
`sheet-metal` skill: model → STEP → meviy quote → order. Browser
workflow with the user's account; report the quoted price/lead time back.

## McMaster-Carr

- The catalog (mcmaster.com) is fast, precise, and most product pages
  offer CAD downloads (STEP/STL/DWG) — grab models for the assembly.
- Part numbers are flat (e.g. `91290A115` = M3×10 SHCS class 12.9);
  search by spec, then verify the detail page matches (thread, length,
  material, grade) before listing it.
- An ordering API exists only for approved business accounts — treat as
  browser workflow otherwise.

## Aluminum Extrusion Systems

For frames/gantries/enclosure skeletons:
- Systems: Misumi HFS (metric 20/30/40 series), 80/20 (inch + metric),
  Bosch Rexroth. Slot compatibility differs — pick ONE system per frame
  and match T-nuts/brackets to its slot (e.g. HFS5 20mm = 6mm slot).
- Deliverable for a frame design: cut list (profile, length, qty),
  connector BOM (brackets, T-nuts, screws), and end-tap callouts.
  Misumi cuts extrusions to length per order — encode lengths in the
  part number rather than planning on-site cuts.

## BOM Deliverable

Build the BOM as a spreadsheet (csv/xlsx) with columns:

`item | qty | description | vendor | part number | unit price | lead time | CAD file | notes`

- Include fasteners and T-nuts — the always-forgotten lines.
- Add 10% spares on small hardware.
- Note price/lead-time volatility: quotes are snapshots; restate the
  retrieval date.
- Drop downloaded STEP files in one folder with names matching BOM items
  so the user can assemble the CAD.

## Pitfalls

- Prices and configurators sit behind logins/regions — if the browser
  session isn't authenticated, report part numbers and let the user
  price them, rather than guessing.
- Don't infer Misumi alteration codes from memory — families change;
  read the configurator page.
- Check stock/lead time on Misumi configured parts: some combinations
  quote weeks, which can flip the build-vs-buy decision.
- Thread standards: match the design (metric vs UNC) across the whole
  BOM; call out any mixed-standard interfaces explicitly.
