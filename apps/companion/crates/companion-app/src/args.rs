//! Command-line interface.

use clap::Parser;

/// Fabric companion — an always-on-top desktop pet that mirrors what your
/// Fabric agent is doing (petdex/Codex-style sprites).
///
/// With no connection flags it starts in demo mode: a procedurally generated
/// placeholder pet cycling through the animation states, roaming enabled.
/// Point it at a running backend (`--url` + `--token`), or let it spawn its
/// own (`--spawn`), to mirror a real session.
#[derive(Debug, Parser)]
#[command(name = "fabric-companion", version, about)]
pub struct Args {
    /// WebSocket URL of a running Fabric backend, e.g.
    /// ws://127.0.0.1:9119/api/ws (the `fabric dashboard` default port).
    #[arg(long, conflicts_with = "spawn")]
    pub url: Option<String>,

    /// Session token for --url (falls back to $FABRIC_COMPANION_TOKEN).
    /// For `fabric dashboard`, the token is injected into the served page;
    /// see the README for how to retrieve it.
    #[arg(long)]
    pub token: Option<String>,

    /// Spawn a private `fabric serve --port 0` backend and connect to it.
    #[arg(long)]
    pub spawn: bool,

    /// The `fabric` executable to use with --spawn.
    #[arg(long, default_value = "fabric")]
    pub fabric_bin: String,

    /// Resume this stored session id instead of creating a fresh session.
    /// CAUTION: resuming re-binds that session's event stream to the
    /// companion — another attached surface stops receiving its events.
    #[arg(long, conflicts_with = "resume_recent")]
    pub session: Option<String>,

    /// Resume the most recent stored session (same caution as --session).
    #[arg(long)]
    pub resume_recent: bool,

    /// Submit one prompt after binding (handy with a fresh session).
    #[arg(long)]
    pub prompt: Option<String>,

    /// Pet slug to display (defaults to the `display.pet.slug` config, then
    /// the first installed pet, then the built-in demo blob).
    #[arg(long)]
    pub pet: Option<String>,

    /// Sprite scale (defaults to `display.pet.scale` from config.yaml).
    #[arg(long)]
    pub scale: Option<f32>,

    /// Disable idle roaming (pet stays put).
    #[arg(long)]
    pub no_roam: bool,

    /// Overlay window width, logical px.
    #[arg(long, default_value_t = 720)]
    pub width: u32,

    /// Overlay window height, logical px.
    #[arg(long, default_value_t = 300)]
    pub height: u32,

    /// Window position (logical px from the primary monitor's top-left).
    /// When omitted the overlay parks itself at the bottom-left of the
    /// primary monitor.
    #[arg(long, num_args = 2, value_names = ["X", "Y"])]
    pub position: Option<Vec<i32>>,

    /// Keep the floor this many px above the window's bottom edge (clears a
    /// taskbar when the overlay hugs the screen bottom).
    #[arg(long, default_value_t = 0.0)]
    pub floor_offset: f32,

    /// Let the window receive mouse input (default: click-through).
    #[arg(long)]
    pub interactive: bool,

    /// Force demo mode even when connection flags are present.
    #[arg(long)]
    pub demo: bool,

    /// Render on an opaque dark backdrop instead of a transparent window
    /// (debugging aid for compositors where transparency misbehaves).
    #[arg(long)]
    pub opaque: bool,
}

impl Args {
    pub fn wants_backend(&self) -> bool {
        !self.demo && (self.url.is_some() || self.spawn)
    }
}
