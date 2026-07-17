//! fabric-companion-core — engine-agnostic logic for the Fabric companion.
//!
//! This crate is the Rust mirror of `agent/pet/` (the canonical Python pet
//! engine) plus the small amount of gateway-protocol parsing the desktop
//! overlay needs. It deliberately has **no** game-engine or windowing
//! dependency so its logic stays cheap to compile, easy to test, and honest
//! about what it is: a port of behavior that is specified elsewhere.
//!
//! Module map (each header comment names the Python file it mirrors):
//!
//! - [`state`]  — activity signals → [`state::PetState`] priority ladder,
//!   conformance-tested against shared vectors generated from Python.
//! - [`atlas`]  — Petdex spritesheet geometry, row taxonomy inference, and
//!   blank-trim frame counting.
//! - [`store`]  — read-only access to `<FABRIC_HOME>/pets/` and the
//!   `display.pet.*` config block.
//! - [`gateway`] — the subset of gateway WebSocket wire events the overlay
//!   consumes, and their mapping onto activity signals.
//!
//! Like every pet surface, the companion is a *display* concern: it adds no
//! model tool, mutates no prompt, and must never write runtime state.

pub mod atlas;
pub mod gateway;
pub mod roam;
pub mod state;
pub mod store;
