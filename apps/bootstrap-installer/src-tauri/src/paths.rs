//! Filesystem paths + logging setup.
//!
//! Mirrors the Python CLI and Electron desktop home resolution:
//!   Windows: %LOCALAPPDATA%\fabric
//!   macOS:   ~/.fabric
//!   Linux:   ~/.fabric
//! `FABRIC_HOME` is canonical. `HERMES_HOME` and legacy default directories
//! remain readable so existing installations upgrade in place.
//!
//! NOTE (macOS): the CLI installer and Electron desktop use a dot-directory;
//! there is no ~/Library/Application Support branch. An earlier
//! version of this file used Application Support, which drifted from every
//! other component: the installer wrote the install to one dir and the
//! desktop looked for it in another, so first launch never found the backend.
//!
//! IMPORTANT: this must match exactly. Drift here means install.ps1
//! writes to one place and the installer reads from another, breaking
//! the bootstrap-complete check.

use std::path::{Path, PathBuf};
#[cfg(target_os = "macos")]
use std::process::Command;
use tracing_appender::non_blocking::WorkerGuard;

/// Returns the canonical Fabric home directory while preserving legacy homes.
pub fn fabric_home() -> PathBuf {
    for key in ["FABRIC_HOME", "HERMES_HOME"] {
        if let Ok(override_path) = std::env::var(key) {
            if !override_path.trim().is_empty() {
                return PathBuf::from(override_path);
            }
        }
    }

    #[cfg(target_os = "windows")]
    {
        // %LOCALAPPDATA%\fabric, with an in-place fallback for old installs.
        if let Some(local_app_data) = dirs::data_local_dir() {
            return prefer_modern_home(
                local_app_data.join("fabric"),
                local_app_data.join("hermes"),
            );
        }
    }

    // macOS + Linux: ~/.fabric, with an in-place fallback for old installs.
    if let Some(home) = dirs::home_dir() {
        return prefer_modern_home(home.join(".fabric"), home.join(".hermes"));
    }

    // Last resort — current dir, almost certainly wrong but at least
    // doesn't panic.
    PathBuf::from(".fabric")
}

fn prefer_modern_home(modern: PathBuf, legacy: PathBuf) -> PathBuf {
    if !modern.exists() && legacy.exists() {
        legacy
    } else {
        modern
    }
}

pub fn log_dir() -> PathBuf {
    fabric_home().join("logs")
}

pub fn log_path() -> PathBuf {
    log_dir().join("bootstrap-installer.log")
}

pub fn bootstrap_cache_dir() -> PathBuf {
    fabric_home().join("bootstrap-cache")
}

/// Resolve the installed source tree. Current installers use `fabric-agent`;
/// old Fabric releases used `hermes-agent`. Prefer Fabric when both exist and
/// retain the legacy fallback so an in-place upgrade can still launch/update.
pub fn install_root_for_home(home: &Path) -> PathBuf {
    let fabric = home.join("fabric-agent");
    let legacy = home.join("hermes-agent");
    if fabric.exists() || !legacy.exists() {
        fabric
    } else {
        legacy
    }
}

pub fn install_root() -> PathBuf {
    install_root_for_home(&fabric_home())
}

/// Preferred stable location for the updater helper.
pub fn installer_dest() -> PathBuf {
    let name = if cfg!(target_os = "windows") {
        "fabric-setup.exe"
    } else {
        "fabric-setup"
    };
    fabric_home().join(name)
}

/// Previous releases and an older desktop may still invoke this exact path.
/// Keep a second copy during the transition so updating either direction is
/// safe; new launchers always prefer `installer_dest()`.
pub fn legacy_installer_dest() -> PathBuf {
    let name = if cfg!(target_os = "windows") {
        "hermes-setup.exe"
    } else {
        "hermes-setup"
    };
    fabric_home().join(name)
}

/// Marker the updater writes for the duration of an in-app update and removes
/// when it finishes (see update.rs `UpdateMarkerGuard`). A freshly-launched
/// desktop checks this before spawning its own local backend: spawning one
/// mid-update re-locks the venv shim and triggers updater process cleanup,
/// which then kills that legitimate backend in a respawn loop (#50238).
///
/// Lives directly under the resolved home (same rationale as `installer_dest`)
/// so the Electron desktop — which resolves both home names identically —
/// the updater's env — agrees on the exact path.
pub fn update_in_progress_marker() -> PathBuf {
    fabric_home().join(".hermes-update-in-progress")
}

/// Copy the currently-running installer binary to both the preferred Fabric
/// helper path and the legacy Fabric helper path. This lets a new Fabric app
/// update an old install and lets an old desktop hand off to a newly installed
/// setup helper during a rolling upgrade.
///
/// No-ops (returns Ok) when the running exe is ALREADY the destination — which
/// is exactly the case during an `--update` run (the desktop launched us FROM
/// that path), where copying onto ourselves would be a Windows sharing
/// violation. Best-effort: a failure here must not fail the install, so the
/// caller logs and continues.
pub fn copy_self_to_fabric_home() -> std::io::Result<()> {
    let src = std::env::current_exe()?;
    copy_installer_to(&src, &installer_dest())?;
    copy_installer_to(&src, &legacy_installer_dest())?;
    Ok(())
}

fn copy_installer_to(src: &Path, dest: &Path) -> std::io::Result<()> {
    // Skip if we're already running from the destination (update re-invocation
    // or a prior copy). canonicalize both so symlinks / 8.3 short paths / case
    // differences don't trick us into a self-copy.
    let same = match (src.canonicalize(), dest.canonicalize()) {
        (Ok(a), Ok(b)) => a == b,
        _ => src == dest,
    };
    if same {
        tracing::info!(?dest, "installer already at destination; skipping self-copy");
        return Ok(());
    }

    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::copy(src, dest)?;
    repair_macos_installer_helper(dest);
    tracing::info!(?src, ?dest, "staged Fabric updater helper");
    Ok(())
}

#[cfg(target_os = "macos")]
fn repair_macos_installer_helper(path: &Path) {
    // The staged helper may inherit quarantine from the downloaded installer.
    // Desktop later launches this exact file for in-app updates, so make it
    // executable before the update handoff reaches LaunchServices/Gatekeeper.
    let _ = Command::new("/usr/bin/xattr")
        .args(["-cr"])
        .arg(path)
        .status();

    let verify = Command::new("/usr/bin/codesign")
        .arg("--verify")
        .arg(path)
        .status();

    if !matches!(verify, Ok(status) if status.success()) {
        let _ = Command::new("/usr/bin/codesign")
            .args(["--force", "--sign", "-"])
            .arg(path)
            .status();
    }
}

#[cfg(not(target_os = "macos"))]
fn repair_macos_installer_helper(_path: &Path) {}

/// Where install.ps1 writes the bootstrap-complete marker (existence-only file
/// the Electron app also checks). Per main.ts:
///   const BOOTSTRAP_COMPLETE_MARKER = path.join(ACTIVE_HERMES_ROOT, '.hermes-bootstrap-complete')
/// We don't always know ACTIVE_HERMES_ROOT until install.ps1 reports it, so
/// this is a probe helper, not a definitive path.
pub fn likely_bootstrap_marker(install_root: &Path) -> PathBuf {
    install_root.join(".hermes-bootstrap-complete")
}

/// Initializes tracing to bootstrap-installer.log under the Fabric home logs.
/// Returns a guard that flushes the appender on drop — keep it alive for
/// the lifetime of the process.
pub fn init_logging() -> Option<WorkerGuard> {
    let dir = log_dir();
    if let Err(err) = std::fs::create_dir_all(&dir) {
        // No log dir → log to stderr only. Don't panic; the installer
        // should still be usable on an exotic filesystem.
        eprintln!("[fabric-setup] could not create log dir {dir:?}: {err}");
        return None;
    }

    let file_appender = tracing_appender::rolling::never(&dir, "bootstrap-installer.log");
    let (non_blocking, guard) = tracing_appender::non_blocking(file_appender);

    let env_filter = tracing_subscriber::EnvFilter::try_from_env("HERMES_BOOTSTRAP_LOG")
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"));

    tracing_subscriber::fmt()
        .with_env_filter(env_filter)
        .with_writer(non_blocking)
        .with_ansi(false)
        .with_target(true)
        .init();

    Some(guard)
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

#[tauri::command]
pub fn get_log_path() -> String {
    log_path().to_string_lossy().into_owned()
}

#[tauri::command]
pub fn get_fabric_home() -> String {
    fabric_home().to_string_lossy().into_owned()
}

/// Primary command name. Existing installs may resolve to a legacy
/// home, while new installs use the canonical Fabric home.
#[tauri::command]
pub fn get_fabric_home() -> String {
    get_fabric_home()
}

#[tauri::command]
pub fn open_log_dir(app: tauri::AppHandle) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    let path = log_dir();
    app.opener()
        .open_path(path.to_string_lossy(), None::<&str>)
        .map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn unique_tmp_dir(tag: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "fabric-setup-paths-{tag}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&path).unwrap();
        path
    }

    #[test]
    fn install_root_prefers_fabric_and_falls_back_to_legacy() {
        let home = unique_tmp_dir("roots");
        let fabric = home.join("fabric-agent");
        let legacy = home.join("hermes-agent");

        assert_eq!(install_root_for_home(&home), fabric);
        std::fs::create_dir_all(&legacy).unwrap();
        assert_eq!(install_root_for_home(&home), legacy);
        std::fs::create_dir_all(&fabric).unwrap();
        assert_eq!(install_root_for_home(&home), fabric);

        let _ = std::fs::remove_dir_all(home);
    }

    #[test]
    fn home_choice_prefers_fabric_and_preserves_an_existing_legacy_home() {
        let base = unique_tmp_dir("home-choice");
        let modern = base.join(".fabric");
        let legacy = base.join(".hermes");

        assert_eq!(prefer_modern_home(modern.clone(), legacy.clone()), modern);
        std::fs::create_dir_all(&legacy).unwrap();
        assert_eq!(prefer_modern_home(modern.clone(), legacy.clone()), legacy);
        std::fs::create_dir_all(&modern).unwrap();
        assert_eq!(prefer_modern_home(modern.clone(), legacy.clone()), modern);

        let _ = std::fs::remove_dir_all(base);
    }

    #[test]
    fn staged_helper_names_cover_fabric_and_legacy() {
        let preferred = installer_dest();
        let legacy = legacy_installer_dest();
        assert!(preferred.file_stem().unwrap().to_string_lossy().contains("fabric-setup"));
        assert!(legacy.file_stem().unwrap().to_string_lossy().contains("hermes-setup"));
        assert_ne!(preferred, legacy);
    }
}
