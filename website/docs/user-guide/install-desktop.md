---
sidebar_position: 4.5
title: "Install Fabric Desktop"
description: "Download, verify, install, and update Fabric Desktop on macOS, Windows, and Linux."
---

# Install Fabric Desktop

Download desktop installers from the official
[Fabric download page](/download). Every published file comes from the
[ObliviousOdin/fabric release](https://github.com/ObliviousOdin/fabric/releases)
named on that page and is recorded in `desktop-release-manifest.json` with its
size, platform, architecture, source commit, and SHA-256 checksum.

The desktop shell and Fabric CLI/backend use separate version numbers:

- the desktop app uses semantic versions such as `0.22.0`;
- the release and Python CLI use a CalVer tag such as `v2026.7.23`;
- the release manifest binds both versions to one exact source commit.

## macOS — Apple silicon

The packaged macOS app currently supports Apple silicon (M1 or later).

1. Download the `.dmg`.
2. Open it and drag **Fabric** into **Applications**.
3. Open Fabric from Applications.
4. Accept Apple's standard first-open confirmation.

Production DMGs and the enclosed app are signed with a Developer ID identity,
notarized by Apple, and stapled for offline verification. Notarization removes
the hard unidentified-developer or malware block; macOS still shows the normal
confirmation the first time you open an internet-downloaded app.

Intel Mac users can use the
[source installation](/getting-started/installation) until a macOS x64 package
is published.

## Windows 10/11 x64

Use the `.exe` for the normal guided installer. The `.msi` is available for
administrative or managed deployment.

The current Windows packages are **unsigned** while the project provisions a
public-trust code-signing identity. Microsoft Defender SmartScreen can
therefore show **Windows protected your PC** and list an unknown publisher.

Before continuing:

1. Download the installer only from the official Fabric download page.
2. Verify its SHA-256 checksum against the release checksum file.
3. In SmartScreen, choose **More info** and then **Run anyway** only when the
   filename and checksum match the official release.

Do not work around SmartScreen for an installer from another site or with a
different checksum. Windows signing will replace this temporary exception; the
release workflow fails unsigned builds unless maintainers keep the explicit
`ALLOW_UNSIGNED_WINDOWS=true` acknowledgment enabled.

## Linux x86_64

- `.AppImage`: make it executable with
  `chmod +x Fabric-<version>-linux-x86_64.AppImage`, then run it.
- `.deb`: install on Debian/Ubuntu with
  `sudo apt install ./Fabric-<version>-linux-amd64.deb`.
- `.rpm`: install with your distribution's RPM package manager using
  `Fabric-<version>-linux-x86_64.rpm`.

Linux packages use checksums rather than platform code signing.

## Verify a download

Download `SHA256SUMS-desktop.txt` from the same GitHub Release.

macOS or Linux:

```bash
shasum -a 256 --ignore-missing -c SHA256SUMS-desktop.txt
```

Windows PowerShell:

```powershell
Get-FileHash .\Fabric-<version>-win-x64.exe -Algorithm SHA256
```

Compare the printed hash with the matching line in
`SHA256SUMS-desktop.txt`. Per-platform checksum files are also attached when
you want a smaller list.

## Updates and version alignment

Fabric Desktop checks the newest official GitHub Release carrying
`desktop-release-manifest.json`.

- A packaged desktop app's **Update now** button opens the matching installer
  download. Run it, then relaunch Fabric.
- On that next launch, a Fabric-managed CLI/backend is aligned to the exact
  source commit stamped into the desktop package before the backend starts.
- A desktop built and run from a source checkout keeps the existing
  `fabric update` plus desktop rebuild flow.
- A remote backend remains independently updatable because it can be deployed
  on a different machine and lifecycle.

The packaged path deliberately does not silently install the current unsigned
Windows executable and does not disable signature verification. Once signed
update feeds are available, background/delta installation can be added without
weakening this boundary.

You can inspect the CLI version at any time:

```bash
fabric version
```
