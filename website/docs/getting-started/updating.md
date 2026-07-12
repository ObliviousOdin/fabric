---
sidebar_position: 3
title: "Updating & Uninstalling"
description: "Safely preview, update, validate, roll back, or remove Fabric and its desktop app."
---

# Updating & Uninstalling

## Preview an update

Check whether the managed Fabric checkout is behind without changing files or
restarting services:

```bash
fabric update --check
```

This fetches release/source metadata and reports the current relationship to the
configured branch.

## Update the engine and source-built desktop

```bash
fabric update
```

For a managed source install, the update path:

1. records a pre-update recovery point for mutable profile state;
2. updates the configured Fabric checkout;
3. validates critical startup modules before accepting the new source;
4. synchronizes Python/Node dependencies;
5. reports configuration migrations;
6. rebuilds a source-built desktop app when its content changed; and
7. restarts managed gateways when safe.

An update is not complete evidence by itself. Validate afterward:

```bash
fabric version
fabric doctor
fabric status --deep
fabric gateway status  # when a gateway is installed
```

:::caution Signed desktop updates are a separate gate
The in-app update button currently drives this managed source-update/rebuild
path. It is not a signed binary auto-update channel. Fabric must publish signed,
checksummed packages plus downgrade/rollback evidence before production desktop
auto-update can be claimed.
:::

## Select a branch deliberately

The default managed branch is `main`. Release owners and QA can select another
branch explicitly:

```bash
fabric update --check --branch release-candidate
fabric update --branch release-candidate
```

Do not point customer machines at an arbitrary contributor branch. A branch
switch can change configuration and state contracts even when the application
still launches.

## Local source changes

Interactive updates preserve local source changes and ask before reapplying
them. Desktop and gateway-triggered updates have no terminal in which to ask;
their policy comes from `config.yaml`:

```yaml title="~/.fabric/config.yaml"
updates:
  non_interactive_local_changes: stash # preserve + restore (default)
  # non_interactive_local_changes: discard
```

Use `discard` only on managed machines whose source tree is never edited. It
does not authorize deletion of profile data.

In Desktop this control appears under **Settings → Advanced → In-App Update
Local Changes**.

## Create a full pre-update backup

For a high-value profile, request a full backup before the source pull:

```bash
fabric update --backup
```

Or make it the profile default:

```yaml title="~/.fabric/config.yaml"
updates:
  pre_update_backup: true
```

Backups must follow the repository's privacy contract: no temporary archive may
be published with permissive permissions, redirect outside the chosen profile,
or silently follow a replaced path. Keep a separately tested off-machine
recovery copy for production operations.

## Desktop-specific precautions

### macOS

A local source rebuild can use ad-hoc signing. A public update must retain Fabric's
Developer ID signature, pass notarization, and preserve the `io.github.obliviousodin.fabric`
bundle identity. If those checks fail, do not bypass Gatekeeper globally.

### Windows

Exit Fabric Desktop and any terminals/gateways using the managed virtual
environment before updating. Windows prevents replacement of a running
`Fabric.exe`, console entry point, Python interpreter, or loaded native module.
The updater should fail with the owning process rather than leaving a
half-updated environment.

### Linux

Source builds update through `fabric update`. AppImage/deb/rpm package updates
remain distribution-specific until Fabric publishes signed/checksummed packages
and an explicit channel policy.

## If the terminal disconnects

The managed updater mirrors its output to:

```text
~/.fabric/logs/update.log
```

Reconnect and inspect the log before starting a second update:

```bash
tail -f ~/.fabric/logs/update.log
```

Starting two mutating updates against the same profile/checkout is unsupported.

## Roll back

Before rollback, identify whether the failure is source, dependency,
configuration, or profile-state related:

```bash
fabric doctor
fabric logs errors -n 100
```

For a source checkout, select a previously verified tag or commit from the
official Fabric repository, reinstall dependencies, and validate the profile.

Configuration/state rollback can have a different compatibility floor from
source rollback. Restore through the documented Fabric snapshot/backup flow and
re-run `fabric config check`; never unpack an archive directly over a running
profile.

## Current release information

Check the [Fabric releases page](https://github.com/ObliviousOdin/fabric/releases).
The absence of a platform asset means it has not been released for that
platform. Unsigned CI artifacts are not production Fabric releases.

## Uninstall only the desktop app

```bash
fabric uninstall --gui
```

This removes desktop build/application data while preserving the engine and
profiles. A source checkout may need `npm ci` before rebuilding later.

## Uninstall the engine

```bash
fabric uninstall
```

The uninstaller asks whether to retain `~/.fabric` so accounts, sessions,
memory, skills, and configuration can survive a reinstall. To remove user data
as well, use the explicit full-removal option and review the confirmation:

```bash
fabric uninstall --full
```

Stop and disable a managed gateway before manual removal:

```bash
fabric gateway stop
fabric gateway uninstall
```
