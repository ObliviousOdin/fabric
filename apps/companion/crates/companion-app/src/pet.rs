//! The Bevy side: sprite animation, activity-driven state, roaming, and the
//! contact shadow. Pure display — all behavior semantics live in
//! `fabric_companion_core` where they are unit- and conformance-tested.

use bevy::prelude::*;
use bevy::window::PrimaryWindow;
use crossbeam_channel::Receiver;
use fabric_companion_core::atlas::{
    roam_walk_row, AtlasGrid, FRAMES_PER_STATE, FRAME_H, FRAME_W, LOOP_MS,
};
use fabric_companion_core::gateway::ActivityTracker;
use fabric_companion_core::roam::{Floor, MotionPose, RoamFrame, RoamLoop, RoamSpec};
use fabric_companion_core::state::{derive_pet_state, PetState};

use crate::bridge::BridgeUpdate;

/// Static facts about the loaded pet, computed once at startup.
#[derive(Resource)]
pub struct PetSpec {
    pub grid: AtlasGrid,
    /// Blank-trimmed frame count per concrete atlas row.
    pub row_frames: Vec<u32>,
    pub scale: f32,
}

impl PetSpec {
    pub fn pet_size(&self) -> Vec2 {
        Vec2::new(FRAME_W as f32 * self.scale, FRAME_H as f32 * self.scale)
    }

    /// Frames in *row*, falling back to the idle row when the row is blank
    /// (ragged sheets), and to 1 as the final floor. State-driven rows are
    /// capped at [`FRAMES_PER_STATE`] (the canonical display-path cap);
    /// directional walk rows play their full physical frame set, matching
    /// the desktop's `framesByRow` pacing.
    fn frames_in(&self, row: u32, state_capped: bool) -> (u32, u32) {
        let cap = if state_capped {
            FRAMES_PER_STATE
        } else {
            u32::MAX
        };
        let count = self.row_frames.get(row as usize).copied().unwrap_or(0);
        if count > 0 {
            return (row, count.min(cap));
        }
        let idle = self.grid.row_for_state(PetState::Idle);
        let idle_count = self.row_frames.get(idle as usize).copied().unwrap_or(0);
        (idle, idle_count.min(cap).max(1))
    }
}

/// Incoming updates from the bridge (or the demo script).
#[derive(Resource)]
pub struct Feed(pub Receiver<BridgeUpdate>);

/// The activity fold — the single source of the pet's mood.
#[derive(Resource, Default)]
pub struct Activity(pub ActivityTracker);

/// Roaming state. `None` loop = roaming disabled.
#[derive(Resource)]
pub struct Roam {
    pub enabled: bool,
    pub floor_offset: f32,
    pub roam_loop: Option<RoamLoop>,
    /// Top-left position of the pet box in window coordinates (y down).
    pub position: Vec2,
}

#[derive(Component, Default)]
pub struct PetSpriteTag {
    row: u32,
    frame: u32,
    acc_ms: f32,
}

pub struct PetPlugin;

impl Plugin for PetPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(Update, (drain_feed, drive_pet).chain());
    }
}

fn now_ms(time: &Time) -> u64 {
    time.elapsed().as_millis() as u64
}

/// Pull bridge updates into the tracker.
fn drain_feed(feed: Res<Feed>, mut activity: ResMut<Activity>, time: Res<Time>) {
    let now = now_ms(&time);
    for update in feed.0.try_iter() {
        match update {
            BridgeUpdate::Bound {
                session_id,
                running,
            } => {
                info!("companion bound to session {session_id}");
                activity.0.seed_running(running);
                // Wave hello — unless the session is mid-turn, where a
                // greeting beat would misreport what the agent is doing.
                if !running {
                    activity.0.greet(now);
                }
            }
            BridgeUpdate::Event(event) => activity.0.apply(&event, now),
            BridgeUpdate::Disconnected => {
                warn!("backend disconnected; retrying");
                // Whatever the dead connection left mid-flight is stale —
                // without this the pet stays pinned in RUN/REVIEW/WAITING
                // for as long as the backend is gone.
                activity.0 = ActivityTracker::new();
            }
        }
    }
}

/// Resolve state → row, tick roaming and the frame clock, and place the
/// sprite. One system so row/frame/position stay coherent within a frame.
#[allow(clippy::too_many_arguments)]
fn drive_pet(
    time: Res<Time>,
    spec: Res<PetSpec>,
    activity: Res<Activity>,
    mut roam: ResMut<Roam>,
    window: Query<&Window, With<PrimaryWindow>>,
    mut query: Query<(&mut PetSpriteTag, &mut Sprite, &mut Transform)>,
) {
    let Ok(window) = window.single() else { return };
    let Ok((mut tag, mut sprite, mut transform)) = query.single_mut() else {
        return;
    };

    let now = now_ms(&time);
    let dt = time.delta_secs();
    let state = derive_pet_state(activity.0.signals(now));
    let pet = spec.pet_size();
    let win = Vec2::new(window.width(), window.height());

    // Keep the roam floor in sync with the current window size.
    let floor = Floor {
        left: 0.0,
        right: (win.x - pet.x).max(0.0),
        y: win.y - roam.floor_offset,
    };

    // Roam only shows through at idle; agent activity always wins.
    let mut motion: Option<RoamFrame> = None;
    if state == PetState::Idle && roam.enabled {
        let frame = match roam.roam_loop.as_mut() {
            Some(active) => active.tick(now as f32, dt, &mut fastrand_f32),
            None => {
                let start = roam.position;
                let spec = RoamSpec {
                    floor,
                    pet_w: pet.x,
                    pet_h: pet.y,
                    loop_ms: LOOP_MS as f32,
                };
                let mut fresh =
                    RoamLoop::new(spec, start.x, start.y, now as f32, &mut fastrand_f32);
                let frame = fresh.tick(now as f32, dt, &mut fastrand_f32);
                roam.roam_loop = Some(fresh);
                frame
            }
        };
        roam.position = Vec2::new(frame.x, frame.y);
        motion = Some(frame);
    } else {
        // Activity interrupts roaming: freeze in place, re-plan on resume.
        if let Some(active) = roam.roam_loop.take() {
            let (x, y) = active.position();
            roam.position = Vec2::new(x, y);
        }
    }

    // Row + mirror. Directional walk rows pace at their full physical frame
    // count; every state-driven row keeps the canonical 6-frame cap. While
    // airborne (and at rest) the inward-facing rule applies, like the
    // desktop's dir-0 fall handling.
    let (row, mirror, walking) = match motion {
        Some(RoamFrame {
            pose: Some(MotionPose::Run),
            dir,
            ..
        }) => match roam_walk_row(&spec.grid, dir) {
            Some(walk) => (walk.row, walk.mirror, true),
            None => (
                spec.grid.row_for_state(PetState::Idle),
                rest_mirror(&roam, pet, win),
                false,
            ),
        },
        Some(RoamFrame {
            pose: Some(MotionPose::Jump),
            ..
        }) => (
            spec.grid.row_for_state(PetState::Jump),
            rest_mirror(&roam, pet, win),
            false,
        ),
        _ => (
            spec.grid.row_for_state(state),
            rest_mirror(&roam, pet, win),
            false,
        ),
    };
    let (row, count) = spec.frames_in(row, !walking);

    // Frame clock: every row loops in ~LOOP_MS regardless of frame count.
    if row != tag.row {
        tag.row = row;
        tag.frame = 0;
        tag.acc_ms = 0.0;
    } else {
        let step_ms = LOOP_MS as f32 / count as f32;
        tag.acc_ms += dt * 1000.0;
        while tag.acc_ms >= step_ms {
            tag.acc_ms -= step_ms;
            tag.frame = (tag.frame + 1) % count;
        }
    }
    tag.frame %= count.max(1);

    if let Some(atlas) = sprite.texture_atlas.as_mut() {
        atlas.index = (row * spec.grid.cols + tag.frame) as usize;
    }
    sprite.flip_x = mirror;

    // Window coords (top-left, y down) → world (centered, y up).
    let top_left = roam.position;
    transform.translation.x = top_left.x + pet.x / 2.0 - win.x / 2.0;
    transform.translation.y = win.y / 2.0 - (top_left.y + pet.y / 2.0);
}

/// Resting facing rule (desktop parity): art faces left by convention; the
/// pet faces inward, so mirror (face right) while it sits in the left half.
fn rest_mirror(roam: &Roam, pet: Vec2, win: Vec2) -> bool {
    roam.position.x + pet.x / 2.0 < win.x / 2.0
}

fn fastrand_f32() -> f32 {
    fastrand::f32()
}
