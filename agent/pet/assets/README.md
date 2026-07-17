# Bundled pets

This directory contains first-party pets that ship with Fabric and remain
available offline. Each pet uses the same `pet.json` plus `spritesheet.webp`
package format as locally generated and Petdex-installed pets.

`fabric-mascot` is the official Fabric emblem companion. Its atlas follows the
current Petdex/Codex contract: eight columns by nine state rows, with 192×208
pixel cells. Validate bundled atlases with the pet generation tests before
shipping them.
