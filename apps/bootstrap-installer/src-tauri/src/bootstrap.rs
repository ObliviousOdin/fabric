//! Bootstrap orchestration.
//!
//! Direct port of `runBootstrap` from `apps/desktop/electron/bootstrap-runner.ts`.
//! Drives install.ps1 / install.sh stage-by-stage, emits progress events
//! over the Tauri `bootstrap` channel, writes a forensic log to
//! HERMES_HOME/logs/bootstrap-<timestamp>.log.
//!
//! Lifecycle:
//!   1. `start_bootstrap` (Tauri command) → spawns the worker task.
//!   2. Worker resolves install script (dev/cache/download).
//!   3. Worker calls `install.ps1 -Manifest` → emits `manifest` event.
//!   4. Worker iterates stages, calling `install.ps1 -Stage NAME -NonInteractive -Json`.
//!   5. On success → `complete`. On any stage failure → `failed`. On cancel → `failed`.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use anyhow::{anyhow, Result};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, State};
use tokio::sync::{mpsc, Mutex};

use crate::events::{BootstrapEvent, LogStream, Manifest, StageState};
use crate::install_script::{self, Pin, ScriptKind, ScriptSource};
use crate::powershell::{self, StreamSink};
use crate::AppState;

// ---------------------------------------------------------------------------
// Public Tauri commands
// ---------------------------------------------------------------------------

/// Frontend → Rust: kick off the install.
#[derive(Debug, Deserialize)]
pub struct StartBootstrapArgs {
    /// Optional override for the commit pin. Defaults to the build-time
    /// pin baked in via `BUILD_PIN_COMMIT`.
    pub commit: Option<String>,
    /// Optional override for the branch pin. Defaults to `BUILD_PIN_BRANCH`.
    pub branch: Option<String>,
    /// Include Stage-Desktop (build apps/desktop) in the manifest. The
    /// signed bootstrap installer passes true; the deprecated Electron-side
    /// bootstrap-runner passes false to avoid building-while-running.
    #[serde(default = "default_true")]
    pub include_desktop: bool,
    /// Optional override for HERMES_HOME. Tests use this; production
    /// almost always falls back to the OS default.
    pub hermes_home: Option<String>,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Serialize)]
pub struct BootstrapStatus {
    pub running: bool,
    pub completed: bool,
    pub install_root: Option<String>,
    pub last_error: Option<String>,
}

/// Handle stored in AppState while a bootstrap run is in flight. Carries
/// the cancellation channel and the most recent terminal status so the
/// frontend can re-query after a window refresh.
pub struct BootstrapHandle {
    pub cancel_tx: mpsc::Sender<()>,
    pub started_at: Instant,
    pub status: BootstrapStatus,
}

#[tauri::command]
pub async fn start_bootstrap(
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
    args: StartBootstrapArgs,
) -> Result<(), String> {
    let mut guard = state.bootstrap.lock().await;
    if let Some(h) = guard.as_ref() {
        if h.status.running {
            return Err("Bootstrap is already running".into());
        }
    }

    let (cancel_tx, cancel_rx) = mpsc::channel::<()>(1);
    let handle = BootstrapHandle {
        cancel_tx,
        started_at: Instant::now(),
        status: BootstrapStatus {
            running: true,
            completed: false,
            install_root: None,
            last_error: None,
        },
    };
    *guard = Some(handle);
    drop(guard);

    let app_for_task = app.clone();
    let state_for_task = state.inner().clone();
    let args_for_task = args;
    let cancel_rx = Arc::new(Mutex::new(Some(cancel_rx)));

    tokio::spawn(async move {
        let result = run_bootstrap(app_for_task.clone(), args_for_task, cancel_rx).await;

        // Reflect terminal state into AppState so get_bootstrap_status()
        // can serve it after the task exits.
        let mut guard = state_for_task.bootstrap.lock().await;
        if let Some(h) = guard.as_mut() {
            h.status.running = false;
            match &result {
                Ok(install_root) => {
                    h.status.completed = true;
                    h.status.install_root = Some(install_root.clone());
                    h.status.last_error = None;
                }
                Err(err) => {
                    h.status.completed = false;
                    h.status.last_error = Some(err.to_string());
                }
            }
        }
    });

    Ok(())
}

#[tauri::command]
pub async fn cancel_bootstrap(state: State<'_, Arc<AppState>>) -> Result<(), String> {
    let guard = state.bootstrap.lock().await;
    if let Some(h) = guard.as_ref() {
        let _ = h.cancel_tx.try_send(());
    }
    Ok(())
}

#[tauri::command]
pub async fn get_bootstrap_status(
    state: State<'_, Arc<AppState>>,
) -> Result<BootstrapStatus, String> {
    let guard = state.bootstrap.lock().await;
    Ok(match guard.as_ref() {
        Some(h) => BootstrapStatus {
            running: h.status.running,
            completed: h.status.completed,
            install_root: h.status.install_root.clone(),
            last_error: h.status.last_error.clone(),
        },
        None => BootstrapStatus {
            running: false,
            completed: false,
            install_root: None,
            last_error: None,
        },
    })
}

/// Spawn the locally-built Fabric desktop binary, then close the installer
/// window. Caller resolves the binary path from `install_root`.
///
/// Returns Err with a human-readable message if the binary doesn't exist
/// (e.g. when Stage-Desktop was skipped) so the frontend can present
/// actionable failure UI rather than silently doing nothing.
#[tauri::command]
pub async fn launch_fabric_desktop(
    app: AppHandle,
    install_root: String,
) -> Result<(), String> {
    let install_root = PathBuf::from(install_root);
    let exe_path = resolve_hermes_desktop_exe(&install_root).ok_or_else(|| {
        format!(
            "Couldn't find a built Fabric desktop at {}. The desktop build step \
             may have been skipped or failed. Run `fabric desktop` from a \
             terminal to build and launch it.",
            install_root.join("apps").join("desktop").join("release").display()
        )
    })?;

    tracing::info!(?exe_path, "launching Fabric desktop");

    // Detach from us — the installer is about to exit. On macOS launch the
    // bundle through LaunchServices instead of exec'ing Contents/MacOS/<name>
    // directly; this matches user double-click/open behavior and avoids cwd /
    // quarantine oddities after a self-update rebuild. Resolution prefers the
    // Fabric bundle/executable but accepts legacy Hermes names.
    let mut cmd = desktop_launch_command(&exe_path, &install_root);
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        // DETACHED_PROCESS = 0x00000008
        cmd.creation_flags(0x0000_0008);
    }

    cmd.spawn().map_err(|e| {
        format!(
            "failed to launch {}: {e}",
            exe_path.display()
        )
    })?;

    // Give Windows ~150ms to actually start the new process before we exit.
    tokio::time::sleep(std::time::Duration::from_millis(150)).await;

    // Exit the installer cleanly. Tauri's process plugin gives us the
    // right hook regardless of platform.
    app.exit(0);
    Ok(())
}

/// Compatibility command for an older packaged webview. New builds invoke
/// `launch_fabric_desktop`; keeping this alias makes mixed-version repair and
/// update handoffs safe.
#[tauri::command]
pub async fn launch_hermes_desktop(
    app: AppHandle,
    install_root: String,
) -> Result<(), String> {
    launch_fabric_desktop(app, install_root).await
}

/// Walk the well-known electron-builder unpacked-app paths under
/// `install_root`. Fabric candidates are deliberately grouped before every
/// legacy Hermes candidate, including across architectures, so a machine with
/// both builds always launches the newly branded app.
pub(crate) fn resolve_hermes_desktop_exe(install_root: &std::path::Path) -> Option<PathBuf> {
    for p in desktop_release_candidates(install_root, std::env::consts::OS) {
        if p.exists() {
            return Some(p);
        }
    }
    None
}

pub(crate) fn desktop_release_candidates(
    install_root: &std::path::Path,
    target_os: &str,
) -> Vec<PathBuf> {
    desktop_release_candidates_for_arch(install_root, target_os, std::env::consts::ARCH)
}

fn desktop_release_candidates_for_arch(
    install_root: &std::path::Path,
    target_os: &str,
    target_arch: &str,
) -> Vec<PathBuf> {
    let release = install_root.join("apps").join("desktop").join("release");
    let arm_first = matches!(target_arch, "aarch64" | "arm64");
    let platform_dirs: &[&str] = match (target_os, arm_first) {
        ("windows", true) => &["win-arm64-unpacked", "win-unpacked"],
        ("windows", false) => &["win-unpacked", "win-arm64-unpacked"],
        ("macos", true) => &["mac-arm64", "mac"],
        ("macos", false) => &["mac", "mac-arm64"],
        (_, true) => &["linux-arm64-unpacked", "linux-unpacked"],
        (_, false) => &["linux-unpacked", "linux-arm64-unpacked"],
    };
    let mut candidates = Vec::new();
    match target_os {
        "windows" => {
            // public-release-audit: allow-legacy-compat -- discover pre-Fabric desktop executables during upgrades
            for exe in ["Fabric.exe", "Hermes.exe"] {
                for dir in platform_dirs {
                    candidates.push(release.join(*dir).join(exe));
                }
            }
        }
        "macos" => {
            // public-release-audit: allow-legacy-compat -- discover pre-Fabric desktop bundles during upgrades
            for (bundle, exe) in [("Fabric.app", "Fabric"), ("Hermes.app", "Hermes")] {
                for dir in platform_dirs {
                    candidates.push(
                        release
                            .join(*dir)
                            .join(bundle)
                            .join("Contents")
                            .join("MacOS")
                            .join(exe),
                    );
                }
            }
        }
        _ => {
            // public-release-audit: allow-legacy-compat -- discover pre-Fabric desktop executables during upgrades
            for exe in ["Fabric", "fabric", "hermes", "Hermes"] {
                for dir in platform_dirs {
                    candidates.push(release.join(*dir).join(exe));
                }
            }
        }
    }
    candidates
}

pub(crate) fn resolve_hermes_desktop_app(install_root: &std::path::Path) -> Option<PathBuf> {
    let exe = resolve_hermes_desktop_exe(install_root)?;
    #[cfg(target_os = "macos")]
    {
        // .../<name>.app/Contents/MacOS/<name> -> .../<name>.app
        let app = exe.parent()?.parent()?.parent()?.to_path_buf();
        if app.extension().and_then(|e| e.to_str()) == Some("app") && app.is_dir() {
            return Some(app);
        }
    }
    #[cfg(not(target_os = "macos"))]
    {
        return Some(exe);
    }
    #[allow(unreachable_code)]
    None
}

/// True when a prior install completed (bootstrap-complete marker present) AND a
/// launchable desktop app exists on disk. Used by the installer's launcher fast
/// path so a bare re-open just opens Fabric instead of re-running setup.
pub(crate) fn hermes_is_installed(install_root: &std::path::Path) -> bool {
    install_root.join(".hermes-bootstrap-complete").exists()
        && resolve_hermes_desktop_exe(install_root).is_some()
}

/// Spawn the already-built desktop app, detached. Returns Err if no built app
/// exists or the spawn fails, so the caller can fall back to showing the
/// installer UI.
pub(crate) fn spawn_installed_desktop(install_root: &std::path::Path) -> std::io::Result<()> {
    let exe = resolve_hermes_desktop_exe(install_root).ok_or_else(|| {
        std::io::Error::new(std::io::ErrorKind::NotFound, "no built Fabric desktop app")
    })?;
    let mut cmd = desktop_launch_command_std(&exe, install_root);
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        // DETACHED_PROCESS = 0x00000008 — keep the desktop alive after the
        // installer exits, mirroring launch_hermes_desktop. Kept correct here
        // even though the only caller is macOS-gated today, so future reuse on
        // Windows doesn't reintroduce the relaunch race.
        cmd.creation_flags(0x0000_0008);
    }
    cmd.spawn().map(|_child| ())
}

#[cfg(target_os = "macos")]
pub(crate) fn open_macos_app_detached(app_bundle: &std::path::Path) -> std::io::Result<()> {
    let mut cmd = std::process::Command::new("/usr/bin/open");
    cmd.arg(app_bundle);
    cmd.current_dir(crate::paths::hermes_home());
    cmd.spawn().map(|_child| ())
}

#[cfg(target_os = "macos")]
fn app_bundle_for_exe(exe: &std::path::Path) -> Option<PathBuf> {
    let app = exe.parent()?.parent()?.parent()?.to_path_buf();
    if app.extension().and_then(|e| e.to_str()) == Some("app") && app.is_dir() {
        Some(app)
    } else {
        None
    }
}

fn desktop_launch_command(
    exe_path: &std::path::Path,
    install_root: &std::path::Path,
) -> tokio::process::Command {
    #[cfg(target_os = "macos")]
    {
        if let Some(app_bundle) = app_bundle_for_exe(exe_path) {
            let mut cmd = tokio::process::Command::new("/usr/bin/open");
            cmd.arg(app_bundle);
            cmd.current_dir(crate::paths::hermes_home());
            return cmd;
        }
    }

    let mut cmd = tokio::process::Command::new(exe_path);
    cmd.current_dir(exe_path.parent().unwrap_or(install_root));
    cmd
}

fn desktop_launch_command_std(
    exe_path: &std::path::Path,
    install_root: &std::path::Path,
) -> std::process::Command {
    #[cfg(target_os = "macos")]
    {
        if let Some(app_bundle) = app_bundle_for_exe(exe_path) {
            let mut cmd = std::process::Command::new("/usr/bin/open");
            cmd.arg(app_bundle);
            cmd.current_dir(crate::paths::hermes_home());
            return cmd;
        }
    }

    let mut cmd = std::process::Command::new(exe_path);
    cmd.current_dir(exe_path.parent().unwrap_or(install_root));
    cmd
}

// ---------------------------------------------------------------------------
// Bootstrap implementation
// ---------------------------------------------------------------------------

async fn run_bootstrap(
    app: AppHandle,
    args: StartBootstrapArgs,
    cancel_rx_holder: Arc<Mutex<Option<mpsc::Receiver<()>>>>,
) -> Result<String> {
    let kind = ScriptKind::for_current_os();

    let pin = Pin {
        commit: args.commit.or_else(|| option_env_string("BUILD_PIN_COMMIT")),
        branch: args.branch.or_else(|| option_env_string("BUILD_PIN_BRANCH")),
    };

    tracing::info!(
        ?pin,
        kind = ?kind,
        include_desktop = args.include_desktop,
        "bootstrap starting"
    );

    let app_for_log = app.clone();
    let emit_log = move |line: &str| {
        emit_event(
            &app_for_log,
            BootstrapEvent::Log {
                stage: None,
                line: line.to_string(),
                stream: LogStream::Stdout,
            },
        );
        // Bump to info-level so the line shows in bootstrap-installer.log
        // under the default INFO filter. Previously this was debug! which
        // got dropped on the floor, leaving us blind whenever install.ps1
        // failed — the log only had the "bootstrap starting" banner.
        tracing::info!(target: "bootstrap.log", "{line}");
    };

    // 1. Resolve install.ps1
    let script = install_script::resolve(kind, &pin, &emit_log)
        .await
        .map_err(|e| {
            let msg = format!("resolve install script failed: {e:#}");
            emit_event(
                &app,
                BootstrapEvent::Failed {
                    stage: None,
                    error: msg.clone(),
                },
            );
            anyhow!(msg)
        })?;

    let source_note = match &script.source {
        ScriptSource::DevCheckout => "dev checkout",
        ScriptSource::Bundled => "bundled",
        ScriptSource::Cached => "cached",
        ScriptSource::Downloaded => "downloaded",
    };
    emit_log(&format!(
        "[bootstrap] script {} via {}",
        script.path.display(),
        source_note
    ));

    // 2. Fetch manifest
    //
    // -IncludeDesktop MUST be passed to the manifest call too — install.ps1
    // gates the desktop stage inclusion on this flag, so without it here
    // the manifest comes back missing the desktop stage and we never run
    // it. The per-stage call below also passes -IncludeDesktop to keep
    // the contracts identical.
    let manifest_args = build_pin_args(&script);
    let mut manifest_args_full = vec!["-Manifest".to_string()];
    manifest_args_full.extend(manifest_args.clone());
    if args.include_desktop {
        manifest_args_full.push("-IncludeDesktop".to_string());
    }

    let manifest_result = run_install_script(
        &app,
        &script.path,
        &manifest_args_full,
        args.hermes_home.as_deref(),
        None,
        Some("__manifest__".to_string()),
    )
    .await?;

    if manifest_result.exit_code != Some(0) {
        let err = format!(
            "install.ps1 -Manifest failed: exit {:?}\n{}",
            manifest_result.exit_code,
            manifest_result.stderr.trim()
        );
        emit_event(
            &app,
            BootstrapEvent::Failed {
                stage: None,
                error: err.clone(),
            },
        );
        return Err(anyhow!(err));
    }

    let mut manifest: Manifest = powershell::parse_manifest(&manifest_result.stdout).ok_or_else(|| {
        let err = format!(
            "install.ps1 -Manifest produced no parseable JSON payload\n{}",
            truncate(&manifest_result.stdout, 4000)
        );
        emit_event(
            &app,
            BootstrapEvent::Failed {
                stage: None,
                error: err.clone(),
            },
        );
        anyhow!(err)
    })?;

    // The stage protocol is an internal compatibility contract shared with
    // legacy installers. Keep stable stage ids/categories, but never leak an
    // legacy product name into the visible progress list.
    for stage in &mut manifest.stages {
        stage.title = fabric_display_copy(&stage.title);
    }

    emit_event(
        &app,
        BootstrapEvent::Manifest {
            stages: manifest.stages.clone(),
            protocol_version: manifest.protocol_version,
        },
    );

    // 3. Iterate stages.
    for stage in &manifest.stages {
        // Skip Stage-Desktop unless explicitly requested. install.ps1 may
        // or may not include it in the manifest depending on the flag we
        // pass, but if it slipped in, gate client-side too.
        if !args.include_desktop && stage.name.eq_ignore_ascii_case("desktop") {
            emit_event(
                &app,
                BootstrapEvent::Stage {
                    name: stage.name.clone(),
                    state: StageState::Skipped,
                    duration_ms: Some(0),
                    result: None,
                    error: Some("skipped by include_desktop=false".into()),
                },
            );
            continue;
        }

        if cancellation_signalled(&cancel_rx_holder).await {
            let err = "bootstrap cancelled by user".to_string();
            emit_event(
                &app,
                BootstrapEvent::Failed {
                    stage: Some(stage.name.clone()),
                    error: err.clone(),
                },
            );
            return Err(anyhow!(err));
        }

        let started = Instant::now();
        emit_event(
            &app,
            BootstrapEvent::Stage {
                name: stage.name.clone(),
                state: StageState::Running,
                duration_ms: None,
                result: None,
                error: None,
            },
        );

        let mut stage_args = vec![
            "-Stage".to_string(),
            stage.name.clone(),
            "-NonInteractive".to_string(),
            "-Json".to_string(),
        ];
        stage_args.extend(manifest_args.clone());
        if args.include_desktop {
            stage_args.push("-IncludeDesktop".to_string());
        }

        // Each stage gets its own cancel receiver because tokio::select!
        // in run_script consumes it. Take/return through the Arc<Mutex>.
        let local_cancel_rx = cancel_rx_holder.lock().await.take();

        let stage_result = run_install_script(
            &app,
            &script.path,
            &stage_args,
            args.hermes_home.as_deref(),
            local_cancel_rx,
            Some(stage.name.clone()),
        )
        .await?;

        let duration_ms = started.elapsed().as_millis() as u64;

        if stage_result.killed {
            emit_event(
                &app,
                BootstrapEvent::Stage {
                    name: stage.name.clone(),
                    state: StageState::Failed,
                    duration_ms: Some(duration_ms),
                    result: None,
                    error: Some("cancelled by user".into()),
                },
            );
            emit_event(
                &app,
                BootstrapEvent::Failed {
                    stage: Some(stage.name.clone()),
                    error: "cancelled by user".into(),
                },
            );
            return Err(anyhow!("cancelled by user"));
        }

        let result_frame = powershell::parse_stage_result(&stage_result.stdout);

        match result_frame {
            None => {
                let err = format!(
                    "install.ps1 -Stage {} produced no JSON result frame (exit={:?})",
                    stage.name, stage_result.exit_code
                );
                emit_event(
                    &app,
                    BootstrapEvent::Stage {
                        name: stage.name.clone(),
                        state: StageState::Failed,
                        duration_ms: Some(duration_ms),
                        result: None,
                        error: Some(err.clone()),
                    },
                );
                emit_event(
                    &app,
                    BootstrapEvent::Failed {
                        stage: Some(stage.name.clone()),
                        error: err.clone(),
                    },
                );
                return Err(anyhow!(err));
            }
            Some(frame) if frame.ok && frame.skipped => {
                emit_event(
                    &app,
                    BootstrapEvent::Stage {
                        name: stage.name.clone(),
                        state: StageState::Skipped,
                        duration_ms: Some(duration_ms),
                        result: Some(frame),
                        error: None,
                    },
                );
            }
            Some(frame) if frame.ok => {
                emit_event(
                    &app,
                    BootstrapEvent::Stage {
                        name: stage.name.clone(),
                        state: StageState::Succeeded,
                        duration_ms: Some(duration_ms),
                        result: Some(frame),
                        error: None,
                    },
                );
            }
            Some(frame) => {
                let err = frame
                    .reason
                    .clone()
                    .map(|reason| fabric_display_copy(&reason))
                    .unwrap_or_else(|| format!("exit code {:?}", stage_result.exit_code));
                emit_event(
                    &app,
                    BootstrapEvent::Stage {
                        name: stage.name.clone(),
                        state: StageState::Failed,
                        duration_ms: Some(duration_ms),
                        result: Some(frame),
                        error: Some(err.clone()),
                    },
                );
                emit_event(
                    &app,
                    BootstrapEvent::Failed {
                        stage: Some(stage.name.clone()),
                        error: err.clone(),
                    },
                );
                return Err(anyhow!(err));
            }
        }
    }

    // 4. Resolve install_root. Current scripts clone to `fabric-agent`; the
    // resolver retains `hermes-agent` as an upgrade fallback.
    let hermes_home = args
        .hermes_home
        .clone()
        .unwrap_or_else(|| crate::paths::hermes_home().to_string_lossy().into_owned());
    let install_root = crate::paths::install_root_for_home(Path::new(&hermes_home));

    // Stage both HERMES_HOME/fabric-setup and its hermes-setup compatibility
    // copy so new and legacy desktops can hand off to the same updater.
    if let Err(err) = crate::paths::copy_self_to_hermes_home() {
        tracing::warn!(?err, "failed to copy installer into HERMES_HOME (non-fatal)");
        emit_log(&format!(
            "[bootstrap] warning: could not stage updater binary: {err}"
        ));
    }

    emit_event(
        &app,
        BootstrapEvent::Complete {
            install_root: install_root.to_string_lossy().into_owned(),
            marker: Some(serde_json::json!({
                "pinnedCommit": pin.commit,
                "pinnedBranch": pin.branch,
            })),
        },
    );

    Ok(install_root.to_string_lossy().into_owned())
}

async fn cancellation_signalled(holder: &Arc<Mutex<Option<mpsc::Receiver<()>>>>) -> bool {
    let mut guard = holder.lock().await;
    if let Some(rx) = guard.as_mut() {
        rx.try_recv().is_ok()
    } else {
        false
    }
}

async fn run_install_script(
    app: &AppHandle,
    script_path: &std::path::Path,
    args: &[String],
    hermes_home_override: Option<&str>,
    cancel_rx: Option<mpsc::Receiver<()>>,
    stage_name: Option<String>,
) -> Result<powershell::ScriptResult> {
    let app_for_stdout = app.clone();
    let stage_for_stdout = stage_name.clone();
    let app_for_stderr = app.clone();
    let stage_for_stderr = stage_name.clone();
    let stage_for_stdout_log = stage_name.clone();
    let stage_for_stderr_log = stage_name.clone();

    let sink = StreamSink {
        on_stdout_line: Box::new(move |line: &str| {
            emit_event(
                &app_for_stdout,
                BootstrapEvent::Log {
                    stage: stage_for_stdout.clone(),
                    line: line.to_string(),
                    stream: LogStream::Stdout,
                },
            );
            // Tee to the rolling installer log so we have a persistent
            // record of every install.ps1 line. Without this, the only
            // log evidence of a failure was the Tauri event stream —
            // which gets discarded the moment the failure route mounts.
            match &stage_for_stdout_log {
                Some(name) => {
                    tracing::info!(target: "bootstrap.log", stage = %name, "{line}")
                }
                None => tracing::info!(target: "bootstrap.log", "{line}"),
            }
        }),
        on_stderr_line: Box::new(move |line: &str| {
            emit_event(
                &app_for_stderr,
                BootstrapEvent::Log {
                    stage: stage_for_stderr.clone(),
                    line: line.to_string(),
                    stream: LogStream::Stderr,
                },
            );
            // stderr-level lines get warn! so they're visually distinct
            // when scrolling through the log later.
            match &stage_for_stderr_log {
                Some(name) => {
                    tracing::warn!(target: "bootstrap.log", stage = %name, "stderr: {line}")
                }
                None => tracing::warn!(target: "bootstrap.log", "stderr: {line}"),
            }
        }),
    };

    powershell::run_script(script_path, args, sink, hermes_home_override, cancel_rx)
        .await
        .map_err(|e| {
            tracing::error!(?e, "install script invocation failed");
            anyhow!("install script invocation failed: {e:#}")
        })
}

fn build_pin_args(script: &install_script::ResolvedScript) -> Vec<String> {
    let mut out = Vec::new();
    if let Some(c) = &script.commit {
        out.push("-Commit".to_string());
        out.push(c.clone());
    }
    if let Some(b) = &script.branch {
        out.push("-Branch".to_string());
        out.push(b.clone());
    }
    out
}

fn emit_event(app: &AppHandle, event: BootstrapEvent) {
    // Tee important state transitions to the rolling installer log so
    // bootstrap-installer.log isn't just "starting" + final summary.
    // Log lines (the noisy stuff) handle their own tracing in
    // run_install_script's sink; here we cover the lifecycle frames.
    match &event {
        BootstrapEvent::Manifest { stages, .. } => {
            tracing::info!(
                stage_count = stages.len(),
                names = ?stages.iter().map(|s| s.name.as_str()).collect::<Vec<_>>(),
                "manifest received"
            );
        }
        BootstrapEvent::Stage {
            name,
            state,
            duration_ms,
            error,
            ..
        } => {
            tracing::info!(
                stage = %name,
                ?state,
                duration_ms = ?duration_ms,
                error = ?error,
                "stage transition"
            );
        }
        BootstrapEvent::Complete { install_root, .. } => {
            tracing::info!(install_root = %install_root, "bootstrap complete");
        }
        BootstrapEvent::Failed { stage, error } => {
            tracing::error!(stage = ?stage, error = %error, "bootstrap FAILED");
        }
        BootstrapEvent::Log { .. } => {
            // Log lines are teed via the sink callbacks in
            // run_install_script — don't double-emit here.
        }
    }
    if let Err(e) = app.emit(BootstrapEvent::CHANNEL, &event) {
        tracing::warn!(?e, "failed to emit bootstrap event");
    }
}

fn option_env_string(key: &str) -> Option<String> {
    // option_env! only accepts literals, so we hardcode the known keys.
    let val = match key {
        "BUILD_PIN_COMMIT" => option_env!("BUILD_PIN_COMMIT"),
        "BUILD_PIN_BRANCH" => option_env!("BUILD_PIN_BRANCH"),
        _ => None,
    };
    val.map(|s| s.to_string())
}

fn truncate(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        format!("{}...", &s[..max])
    }
}

fn fabric_display_copy(value: &str) -> String {
    value
        .replace("Fabric AGENT", "FABRIC")
        .replace("Fabric Agent", "Fabric")
        // public-release-audit: allow-legacy-compat -- normalize copy returned by older installers
        .replace("Hermes", "Fabric")
        .replace("`fabric`", "`fabric`")
        .replace("Fabric command", "fabric command")
        // public-release-audit: allow-legacy-compat -- normalize home guidance returned by older installers
        .replace("~/.hermes", "~/.fabric")
        // public-release-audit: allow-legacy-compat -- normalize Windows home guidance returned by older installers
        .replace("%LOCALAPPDATA%\\hermes", "%LOCALAPPDATA%\\fabric")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn unique_tmp_dir(tag: &str) -> PathBuf {
        let base = std::env::temp_dir().join(format!(
            "hermes-bootstrap-test-{tag}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&base).unwrap();
        base
    }

    // Build a fake built-desktop release tree at the platform's expected path
    // and return (install_root, expected_app_bundle_or_exe).
    fn make_release_tree(install_root: &Path, branded: bool) -> PathBuf {
        let release = install_root.join("apps").join("desktop").join("release");
        if cfg!(target_os = "macos") {
            // public-release-audit: allow-legacy-compat -- exercise upgrades from pre-Fabric desktop bundles
            let app_name = if branded { "Fabric.app" } else { "Hermes.app" };
            // public-release-audit: allow-legacy-compat -- exercise upgrades from pre-Fabric desktop executables
            let exe_name = if branded { "Fabric" } else { "Hermes" };
            let macos_dir = release
                .join("mac-arm64")
                .join(app_name)
                .join("Contents")
                .join("MacOS");
            std::fs::create_dir_all(&macos_dir).unwrap();
            std::fs::write(macos_dir.join(exe_name), b"#!/bin/sh\n").unwrap();
            macos_dir.parent().unwrap().parent().unwrap().to_path_buf()
        } else if cfg!(target_os = "windows") {
            let dir = release.join("win-unpacked");
            std::fs::create_dir_all(&dir).unwrap();
            // public-release-audit: allow-legacy-compat -- exercise upgrades from pre-Fabric Windows executables
            let exe = dir.join(if branded { "Fabric.exe" } else { "Hermes.exe" });
            std::fs::write(&exe, b"stub").unwrap();
            exe
        } else {
            let dir = release.join("linux-unpacked");
            std::fs::create_dir_all(&dir).unwrap();
            let exe = dir.join(if branded { "fabric" } else { "hermes" });
            std::fs::write(&exe, b"stub").unwrap();
            exe
        }
    }

    // The relaunch / install target is derived from the rebuilt desktop app.
    // On macOS this MUST resolve to the .app bundle (what `open` relaunches and
    // what the updater ditto's over /Applications/Hermes.app). A regression in
    // this derivation breaks the post-update auto-relaunch, so guard it.
    #[test]
    fn resolve_hermes_desktop_app_finds_built_bundle() {
        let root = unique_tmp_dir("app-ok");
        let expected = make_release_tree(&root, true);

        let resolved = resolve_hermes_desktop_app(&root)
            .expect("should resolve the freshly-built desktop app");

        #[cfg(target_os = "macos")]
        {
            assert_eq!(resolved, expected, "must resolve to the .app bundle");
            assert_eq!(
                resolved.extension().and_then(|e| e.to_str()),
                Some("app"),
                "relaunch target must be a .app bundle on macOS"
            );
        }
        #[cfg(not(target_os = "macos"))]
        {
            assert_eq!(resolved, expected);
        }
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn desktop_resolution_prefers_fabric_and_accepts_legacy_hermes() {
        let root = unique_tmp_dir("preference");
        let legacy = make_release_tree(&root, false);
        let legacy_exe = resolve_hermes_desktop_exe(&root).expect("legacy app remains launchable");
        #[cfg(target_os = "macos")]
        assert!(legacy_exe.starts_with(&legacy));
        #[cfg(not(target_os = "macos"))]
        assert_eq!(legacy_exe, legacy);

        let fabric = make_release_tree(&root, true);
        let preferred = resolve_hermes_desktop_exe(&root).expect("Fabric app is launchable");
        #[cfg(target_os = "macos")]
        assert!(preferred.starts_with(&fabric));
        #[cfg(not(target_os = "macos"))]
        assert_eq!(preferred, fabric);

        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn every_desktop_platform_lists_fabric_before_hermes() {
        let root = Path::new("/install");
        for os in ["windows", "macos", "linux"] {
            let names: Vec<String> = desktop_release_candidates(root, os)
                .iter()
                .map(|p| p.to_string_lossy().into_owned())
                .collect();
            let first_legacy = names
                .iter()
                .position(|p| p.to_ascii_lowercase().contains("hermes"))
                .expect("legacy candidate is retained");
            assert!(
                names[..first_legacy]
                    .iter()
                    .any(|p| p.to_ascii_lowercase().contains("fabric")),
                "{os} must prefer a Fabric candidate"
            );
            assert!(
                names[first_legacy..]
                    .iter()
                    .all(|p| !p.to_ascii_lowercase().contains("fabric")),
                "all Fabric candidates must precede historical candidates on {os}"
            );
        }
    }

    #[test]
    fn desktop_resolution_prefers_native_architecture_within_each_brand() {
        let root = Path::new("/install");
        let arm = desktop_release_candidates_for_arch(root, "macos", "aarch64");
        assert!(arm[0].to_string_lossy().contains("mac-arm64/Fabric.app"));
        let intel = desktop_release_candidates_for_arch(root, "macos", "x86_64");
        assert!(intel[0].to_string_lossy().contains("mac/Fabric.app"));

        let win_arm = desktop_release_candidates_for_arch(root, "windows", "aarch64");
        assert!(win_arm[0].to_string_lossy().contains("win-arm64-unpacked/Fabric.exe"));
        let win_x64 = desktop_release_candidates_for_arch(root, "windows", "x86_64");
        assert!(win_x64[0].to_string_lossy().contains("win-unpacked/Fabric.exe"));
    }

    #[test]
    fn resolve_hermes_desktop_app_is_none_without_a_build() {
        let root = unique_tmp_dir("app-none");
        // No release tree created.
        assert!(
            resolve_hermes_desktop_app(&root).is_none(),
            "no resolved app when nothing has been built"
        );
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn customer_stage_copy_is_fabric_branded_without_touching_compat_paths() {
        assert_eq!(
            fabric_display_copy("Download Fabric and install Fabric command"),
            "Download Fabric and install fabric command"
        );
        // public-release-audit: allow-legacy-compat -- verify conversion of the previous home-directory token
        assert_eq!(fabric_display_copy("~/.hermes"), "~/.fabric");
        assert_eq!(fabric_display_copy("Fabric AGENT"), "FABRIC");
    }
}
