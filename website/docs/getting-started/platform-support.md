---
sidebar_position: 2.5
title: "Platform Support"
description: "Fabric operating-system, architecture, desktop-package, and release-support matrix."
---

# Platform Support

Fabric separates a target that builds from a platform that has passed the
full release contract. A Tier 1 release requires clean installation, update,
repair, rollback, uninstall, signing/checksum verification, and core end-to-end
tests on that platform.

## Tier 1 — release blocking

| Platform                      | Engine surface                                                                                                       | Desktop surface                                      | Current distribution                                                                         |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| **macOS 13+ arm64**           | CLI, TUI, gateway, dashboard                                                                                         | Native `Fabric` app; DMG + zip package target  | Public source checkout; packaged release requires Developer ID signing + notarization        |
| **Windows 10/11 x64**         | Native CLI/TUI/gateway/dashboard, subject to the [Windows feature matrix](/user-guide/windows-native#feature-matrix) | Native `Fabric` app; NSIS + MSI package target | Package CI target; public installer requires Authenticode signing and clean-machine evidence |
| **Ubuntu 22.04/24.04 x86_64** | Headless CLI, gateway, dashboard, services                                                                           | Linux desktop packages are preview                   | Public source checkout                                                                       |
| **Docker Linux amd64**        | Headless engine and gateway                                                                                          | No desktop shell in the container                    | An immutable Fabric-owned image reference supplied by the release owner                       |

Tier 1 is the intended support contract. A row is not proof that a signed
installer is already public. Check the
[Fabric release page](https://github.com/ObliviousOdin/fabric/releases)
for actual release assets and checksums.

## Tier 2

Nightly and support validation:

| Platform           | Policy                                                                        |
| ------------------ | ----------------------------------------------------------------------------- |
| macOS x86_64       | Compatibility/nightly target; not a release-blocking desktop architecture     |
| Windows arm64      | Compatibility/nightly target; native installer evidence is still required     |
| Linux arm64        | Headless and package compatibility target                                     |
| WSL2               | Supported source environment; native Windows and WSL profiles remain separate |
| Docker Linux arm64 | Multi-architecture image target once an immutable Fabric image is published    |

Tier 2 failures block a claim that the affected platform is fully supported, but
do not block an unrelated Tier 1 hotfix.

## Tier 3 — experimental

- Android through Termux
- Nix/NixOS
- Linux distributions outside the recorded Ubuntu clean-machine matrix
- custom or repackaged desktop installers

These paths can work, but they carry explicit limitations and do not inherit the
Tier 1 release promise.

## Desktop packaging contract

The canonical desktop identity comes from
`apps/desktop/branding/fabric.json`. Native packaging CI must build on the native
host and produce the manifest-derived artifact stem:

| CI host     | Required outputs                                            |
| ----------- | ----------------------------------------------------------- |
| macOS arm64 | `Fabric-<version>-mac-arm64.dmg`, `.zip`              |
| Windows x64 | `Fabric-<version>-win-x64.exe`, `.msi`                |
| Linux x64   | `Fabric-<version>-linux-x64.AppImage`, `.deb`, `.rpm` |

CI outputs are short-lived, unsigned verification artifacts. A production
desktop release additionally needs:

1. a Fabric-controlled signing identity for macOS and Windows;
2. Apple notarization and staple verification for macOS;
3. Authenticode verification for both Windows formats;
4. checksums generated after signing;
5. clean-machine install, launch, update, rollback, and uninstall evidence; and
6. publication under `ObliviousOdin/fabric`.

## Source-install boundary

The verified Fabric installation starts from the public
`ObliviousOdin/fabric` checkout. Signed
desktop packages remain release gates until they are present and independently
verified. Follow [Install Fabric](/getting-started/installation), and only trust
release assets published by the official repository.

```bash
fabric version
```
