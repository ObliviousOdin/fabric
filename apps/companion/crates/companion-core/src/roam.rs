//! Idle roaming: the pet loafs, strolls, and gravity-drops along a floor.
//!
//! Rust mirror of the Electron desktop's roam loop
//! (`apps/desktop/src/components/pet/roam-behavior.ts` +
//! `use-pet-roam.ts`), with one deliberate simplification: the desktop
//! measures in-app DOM perches (composer, profile rail, status bar) to hop
//! between, while an OS overlay has exactly one surface — the monitor
//! work-area floor. The decision cadence, stroll targeting, foot-synced walk
//! speed, and fall physics keep the original constants so the two pets move
//! with the same character; the hop branch simply never fires with a single
//! ledge.
//!
//! Roaming only runs while the pet is at rest (idle state) — agent activity
//! always wins. The host is expected to stop ticking (and let the pet react
//! in place) whenever [`crate::state::derive_pet_state`] returns anything but
//! idle, then resume from the same position.

/// Mean of the exponential dwell between decision beats, ms.
pub const PAUSE_DWELL_MEAN_MS: f32 = 4200.0;
/// Dwell clamp floor, ms.
pub const PAUSE_DWELL_MIN_MS: f32 = 1500.0;
/// Dwell clamp ceiling, ms.
pub const PAUSE_DWELL_MAX_MS: f32 = 13000.0;
/// Chance per beat to keep loafing instead of moving.
pub const REST_CHANCE: f32 = 0.62;
/// Minimum stroll distance as a fraction of the walkable span.
pub const STROLL_MIN_FRACTION: f32 = 0.45;
/// Minimum stroll distance, px.
pub const STROLL_MIN_PX: f32 = 110.0;
/// Probability of strolling toward the roomier side.
pub const STROLL_TOWARD_ROOM: f32 = 0.85;
/// Body-widths traveled per animation loop — walk speed is foot-synced:
/// `speed = pet_w * STRIDE_PER_LOOP / (loop_ms / 1000)`.
pub const STRIDE_PER_LOOP: f32 = 0.8;
/// Fall acceleration, px/s².
pub const GRAVITY_PX_S2: f32 = 5200.0;
/// Arrival threshold, px.
pub const ARRIVE_EPS: f32 = 1.5;
/// Per-tick dt clamp, seconds (throttled-host teleport guard).
pub const MAX_DT_S: f32 = 0.05;
/// The sprite has transparent padding below the feet; rest the box this many
/// px past the floor line so the feet touch it.
pub const FEET_DROP_PX: f32 = 4.0;
/// Initial pause range when the loop starts, ms.
pub const INITIAL_PAUSE_MS: (f32, f32) = (400.0, 1200.0);

/// Uniform-random source in `[0, 1)`. Injected so hosts pick their RNG and
/// tests replay deterministic sequences.
pub trait RoamRng {
    fn next(&mut self) -> f32;
}

impl<F: FnMut() -> f32> RoamRng for F {
    fn next(&mut self) -> f32 {
        self()
    }
}

/// Memoryless dwell: `clamp(-ln(1 - r) * mean, min, max)`.
pub fn dwell_ms(rng: &mut impl RoamRng) -> f32 {
    let r = rng.next().clamp(0.0, 0.999_999);
    (-(1.0 - r).ln() * PAUSE_DWELL_MEAN_MS).clamp(PAUSE_DWELL_MIN_MS, PAUSE_DWELL_MAX_MS)
}

/// The single walkable surface. `left..=right` bounds the pet's left edge;
/// `y` is the floor line the feet rest on.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Floor {
    pub left: f32,
    pub right: f32,
    pub y: f32,
}

impl Floor {
    /// Y for the pet box's top edge when resting on this floor.
    pub fn rest_y(&self, pet_h: f32) -> f32 {
        self.y - pet_h + FEET_DROP_PX
    }
}

/// Pick a stroll destination for a pet whose left edge is at `x`: at least
/// `max(45% of span, 110 px)` away (capped by the room available), heading
/// toward the roomier side 85% of the time. Mirrors `pickStrollTarget`.
pub fn pick_stroll_target(floor: &Floor, x: f32, rng: &mut impl RoamRng) -> f32 {
    let span = floor.right - floor.left;
    if span <= 4.0 {
        return floor.left;
    }
    let room_left = x - floor.left;
    let room_right = floor.right - x;
    let go_right = (rng.next() < STROLL_TOWARD_ROOM) == (room_right >= room_left);
    let room = if go_right { room_right } else { room_left };
    let min_dist = (span * STROLL_MIN_FRACTION).max(STROLL_MIN_PX).min(room);
    let dist = min_dist + rng.next() * (room - min_dist);
    if go_right {
        x + dist
    } else {
        x - dist
    }
}

/// The motion pose roaming asks the sprite to show. Composition rule (same
/// as the desktop's `$petState`): the roam pose shows through **only when
/// the activity state is idle** — real agent activity always wins.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MotionPose {
    /// Walking — pair with the directional walk row (see
    /// [`crate::atlas`]'s taxonomy: `running-right` / `running-left`).
    Run,
    /// Airborne (falling in).
    Jump,
}

/// One tick's output: where the pet box's top-left is, what pose the sprite
/// should show (None = at rest), and the horizontal travel direction
/// (-1 / 0 / 1) for walk-row selection and mirroring.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RoamFrame {
    pub x: f32,
    pub y: f32,
    pub pose: Option<MotionPose>,
    pub dir: i8,
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum Phase {
    Pause { until_ms: f32 },
    Walk { target_x: f32 },
    Fall { vel: f32 },
}

/// Static parameters of a roam loop: where the pet may walk and how big it
/// is (walk speed is derived — foot-synced to the animation loop).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RoamSpec {
    pub floor: Floor,
    pub pet_w: f32,
    pub pet_h: f32,
    pub loop_ms: f32,
}

/// The roam state machine. Advance it with [`RoamLoop::tick`] every frame
/// while the pet is idle; freeze (stop ticking) during agent activity.
#[derive(Debug, Clone, PartialEq)]
pub struct RoamLoop {
    pet_h: f32,
    walk_speed: f32,
    floor: Floor,
    x: f32,
    y: f32,
    phase: Phase,
}

impl RoamLoop {
    /// Start a roam loop at (`x`, `y`). Desktop parity: the loop always
    /// parks first (400–1200 ms), and the pause-expiry planner is what
    /// notices the pet is airborne and begins the drop.
    pub fn new(spec: RoamSpec, x: f32, y: f32, now_ms: f32, rng: &mut impl RoamRng) -> Self {
        let RoamSpec {
            floor,
            pet_w,
            pet_h,
            loop_ms,
        } = spec;
        let walk_speed = pet_w * STRIDE_PER_LOOP / (loop_ms / 1000.0);
        let x = x.clamp(floor.left, floor.right.max(floor.left));
        let (lo, hi) = INITIAL_PAUSE_MS;
        let phase = Phase::Pause {
            until_ms: now_ms + lo + rng.next() * (hi - lo),
        };
        RoamLoop {
            pet_h,
            walk_speed,
            floor,
            x,
            y,
            phase,
        }
    }

    /// Current position without advancing.
    pub fn position(&self) -> (f32, f32) {
        (self.x, self.y)
    }

    /// Move the pet (drag release, external reposition). Desktop parity:
    /// settle for 90 ms first; the planner then drops the pet to the floor
    /// if the new spot is airborne.
    pub fn place(&mut self, x: f32, y: f32, now_ms: f32) {
        self.x = x.clamp(self.floor.left, self.floor.right.max(self.floor.left));
        self.y = y;
        self.phase = Phase::Pause {
            until_ms: now_ms + 90.0,
        };
    }

    fn begin_pause(&mut self, now_ms: f32, rng: &mut impl RoamRng) {
        self.phase = Phase::Pause {
            until_ms: now_ms + dwell_ms(rng),
        };
    }

    /// Advance by `dt_s` seconds (clamped to [`MAX_DT_S`]).
    pub fn tick(&mut self, now_ms: f32, dt_s: f32, rng: &mut impl RoamRng) -> RoamFrame {
        let dt = dt_s.clamp(0.0, MAX_DT_S);
        match self.phase {
            Phase::Fall { mut vel } => {
                vel += GRAVITY_PX_S2 * dt;
                self.y += vel * dt;
                let rest_y = self.floor.rest_y(self.pet_h);
                if self.y >= rest_y {
                    self.y = rest_y;
                    self.begin_pause(now_ms, rng);
                    return RoamFrame {
                        x: self.x,
                        y: self.y,
                        pose: None,
                        dir: 0,
                    };
                }
                self.phase = Phase::Fall { vel };
                RoamFrame {
                    x: self.x,
                    y: self.y,
                    pose: Some(MotionPose::Jump),
                    dir: 0,
                }
            }
            Phase::Pause { until_ms } => {
                if now_ms >= until_ms {
                    // Planner (mirrors planNext): fix vertical mismatch
                    // before considering a move — a parked-then-airborne pet
                    // drops to the floor first.
                    if (self.y - self.floor.rest_y(self.pet_h)).abs() > 2.0 {
                        self.phase = Phase::Fall { vel: 0.0 };
                    } else if rng.next() < REST_CHANCE {
                        self.begin_pause(now_ms, rng);
                    } else {
                        let target = pick_stroll_target(&self.floor, self.x, rng);
                        self.phase = Phase::Walk { target_x: target };
                    }
                }
                RoamFrame {
                    x: self.x,
                    y: self.y,
                    pose: None,
                    dir: 0,
                }
            }
            Phase::Walk { target_x } => {
                let remaining = target_x - self.x;
                let step = self.walk_speed * dt;
                if remaining.abs() <= ARRIVE_EPS.max(step) {
                    self.x = target_x;
                    self.begin_pause(now_ms, rng);
                    return RoamFrame {
                        x: self.x,
                        y: self.y,
                        pose: None,
                        dir: 0,
                    };
                }
                let dir = if remaining > 0.0 { 1 } else { -1 };
                self.x += dir as f32 * step;
                RoamFrame {
                    x: self.x,
                    y: self.y,
                    pose: Some(MotionPose::Run),
                    dir,
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Deterministic RNG replaying a fixed sequence (cycles).
    struct Seq(Vec<f32>, usize);
    impl Seq {
        fn new(values: &[f32]) -> Self {
            Seq(values.to_vec(), 0)
        }
    }
    impl RoamRng for Seq {
        fn next(&mut self) -> f32 {
            let v = self.0[self.1 % self.0.len()];
            self.1 += 1;
            v
        }
    }

    const FLOOR: Floor = Floor {
        left: 0.0,
        right: 1000.0,
        y: 800.0,
    };
    const PET_W: f32 = 63.36; // 192 * 0.33
    const PET_H: f32 = 68.64; // 208 * 0.33
    const SPEC: RoamSpec = RoamSpec {
        floor: FLOOR,
        pet_w: PET_W,
        pet_h: PET_H,
        loop_ms: 1100.0,
    };

    #[test]
    fn dwell_is_clamped() {
        assert_eq!(dwell_ms(&mut Seq::new(&[0.0])), PAUSE_DWELL_MIN_MS);
        assert_eq!(dwell_ms(&mut Seq::new(&[0.9999])), PAUSE_DWELL_MAX_MS);
        let mid = dwell_ms(&mut Seq::new(&[0.5]));
        assert!((mid - 0.5f32.ln().abs() * PAUSE_DWELL_MEAN_MS).abs() < 1.0);
    }

    #[test]
    fn foot_synced_walk_speed() {
        let mut rng = Seq::new(&[0.5]);
        let roam = RoamLoop::new(SPEC, 100.0, FLOOR.rest_y(PET_H), 0.0, &mut rng);
        // 63.36 px * 0.8 / 1.1 s ≈ 46.08 px/s — the desktop's documented rate.
        assert!((roam.walk_speed - 46.08).abs() < 0.1);
    }

    #[test]
    fn stroll_min_distance_and_room_bias() {
        // Pet near the left edge; roomier side is right. First draw (0.1) <
        // 0.85 → toward room (right); second draw 0.0 → minimum distance.
        let mut rng = Seq::new(&[0.1, 0.0]);
        let target = pick_stroll_target(&FLOOR, 50.0, &mut rng);
        let min_dist = (1000.0f32 * STROLL_MIN_FRACTION).max(STROLL_MIN_PX); // 450
        assert_eq!(target, 50.0 + min_dist);

        // Draw ≥ 0.85 → defy the bias, head for the cramped side.
        let mut rng = Seq::new(&[0.9, 0.0]);
        let target = pick_stroll_target(&FLOOR, 50.0, &mut rng);
        assert!(target < 50.0);
        assert!(target >= FLOOR.left - 0.001); // min distance capped by room

        // Degenerate span parks at the left edge.
        let tiny = Floor {
            left: 10.0,
            right: 13.0,
            y: 800.0,
        };
        assert_eq!(pick_stroll_target(&tiny, 12.0, &mut Seq::new(&[0.5])), 10.0);
    }

    #[test]
    fn parks_then_falls_and_lands() {
        let mut rng = Seq::new(&[0.5]);
        let mut roam = RoamLoop::new(SPEC, 100.0, 0.0, 0.0, &mut rng);
        let mut now = 0.0;
        let mut saw_fall = false;
        let mut landed = false;
        for _ in 0..600 {
            now += 16.0;
            let frame = roam.tick(now, 0.016, &mut rng);
            match frame.pose {
                Some(MotionPose::Jump) => {
                    saw_fall = true;
                    assert_eq!(frame.dir, 0);
                }
                None if saw_fall => {
                    landed = true;
                    assert_eq!(frame.y, FLOOR.rest_y(PET_H));
                    break;
                }
                // Initial park (400 + 0.5*800 = 800 ms) plus one planner tick.
                None => assert!(now <= 820.0, "still parked at {now} ms"),
                other => panic!("unexpected pose while falling: {other:?}"),
            }
        }
        assert!(landed, "pet never landed");
    }

    #[test]
    fn loafs_then_strolls_then_pauses() {
        // rest-check draw 0.99 (> REST_CHANCE → move), toward-room 0.1,
        // distance 0.0, then dwell draws 0.5 forever.
        let mut rng = Seq::new(&[0.5]);
        let rest_y = FLOOR.rest_y(PET_H);
        let mut roam = RoamLoop::new(SPEC, 100.0, rest_y, 0.0, &mut rng);

        // Sit through the initial pause (400 + 0.5*800 = 800 ms).
        let frame = roam.tick(500.0, 0.016, &mut rng);
        assert_eq!((frame.pose, frame.dir), (None, 0));

        let mut rng = Seq::new(&[0.99, 0.1, 0.0, 0.5]);
        let frame = roam.tick(900.0, 0.016, &mut rng);
        assert_eq!(frame.pose, None); // decision tick itself doesn't move

        // Now walking right toward x = 100 + 450.
        let frame = roam.tick(916.0, 0.016, &mut rng);
        assert_eq!(frame.pose, Some(MotionPose::Run));
        assert_eq!(frame.dir, 1);
        assert!(frame.x > 100.0);

        // Fast-forward: keep ticking until arrival snaps to the target.
        let mut now = 916.0;
        for _ in 0..2000 {
            now += 16.0;
            let frame = roam.tick(now, 0.016, &mut rng);
            if frame.pose.is_none() {
                assert!((frame.x - 550.0).abs() < 0.001);
                return;
            }
        }
        panic!("stroll never arrived");
    }

    #[test]
    fn rest_chance_keeps_loafing() {
        let rest_y = FLOOR.rest_y(PET_H);
        let mut rng = Seq::new(&[0.5]);
        let mut roam = RoamLoop::new(SPEC, 100.0, rest_y, 0.0, &mut rng);
        // Decision draw 0.3 < 0.62 → loaf again (dwell draw 0.5).
        let mut rng = Seq::new(&[0.3, 0.5]);
        let frame = roam.tick(10_000.0, 0.016, &mut rng);
        assert_eq!((frame.pose, frame.dir), (None, 0));
        assert!(matches!(roam.phase, Phase::Pause { .. }));
    }

    #[test]
    fn dt_clamp_prevents_teleport() {
        let rest_y = FLOOR.rest_y(PET_H);
        let mut rng = Seq::new(&[0.99, 0.1, 0.0, 0.5]);
        let mut roam = RoamLoop::new(SPEC, 100.0, rest_y, 0.0, &mut rng);
        roam.phase = Phase::Walk { target_x: 900.0 };
        // A 5-second stall advances at most MAX_DT_S worth of travel.
        let frame = roam.tick(0.0, 5.0, &mut rng);
        assert!(frame.x - 100.0 <= roam.walk_speed * MAX_DT_S + 0.001);
    }

    #[test]
    fn place_settles_then_replans() {
        let mut rng = Seq::new(&[0.5]);
        let rest_y = FLOOR.rest_y(PET_H);
        let mut roam = RoamLoop::new(SPEC, 200.0, rest_y, 0.0, &mut rng);

        // Airborne placement: 90 ms settle, then the planner starts the drop.
        roam.place(300.0, 0.0, 0.0);
        assert!(matches!(roam.phase, Phase::Pause { .. }));
        let frame = roam.tick(50.0, 0.016, &mut rng);
        assert_eq!(frame.pose, None); // still settling
        roam.tick(95.0, 0.016, &mut rng); // planner tick → fall begins
        let frame = roam.tick(111.0, 0.016, &mut rng);
        assert_eq!(frame.pose, Some(MotionPose::Jump));

        // Grounded placement just settles back into a pause.
        roam.place(300.0, rest_y, 1000.0);
        assert!(matches!(roam.phase, Phase::Pause { .. }));
    }
}
