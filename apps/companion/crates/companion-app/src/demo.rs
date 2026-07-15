//! Procedural placeholder pet: a Codex-contract spritesheet generated at
//! startup so `--demo` runs with zero downloaded assets.
//!
//! The sheet follows `agent/pet/generate/atlas.py` exactly — 1536×1872 px,
//! 8 columns × 9 rows of 192×208 cells, per-row frame counts from
//! `ROW_SPECS` with trailing cells left fully transparent (which exercises
//! the renderer's blank-trim path the same way real petdex art does). The
//! creature itself is a simple pixel blob in Fabric brand colors; install a
//! real pet with `fabric pets install <slug>` for actual art.

use crossbeam_channel::Sender;
use fabric_companion_core::atlas::{FRAME_H, FRAME_W};
use fabric_companion_core::gateway::Event;
use image::{Rgba, RgbaImage};
use std::f32::consts::PI;
use std::time::Duration;

use crate::bridge::BridgeUpdate;

/// With no backend configured, replay a scripted turn so every animation
/// state shows: greet → idle → thinking → tool → waiting → celebrate → and
/// one failure — then loaf a while (roaming shows through) and loop.
pub fn spawn_demo_feed(tx: Sender<BridgeUpdate>) {
    const SCRIPT: &[(u64, &str)] = &[
        (2500, "message.start"),
        (600, "reasoning.delta"),
        (3000, "tool.start"),
        (2600, "tool.complete"),
        (400, "reasoning.delta"),
        (1800, "clarify.request"),
        (3200, "message.complete"),
        (12_000, "message.start"),
        (900, "tool.start"),
        (2400, "error"),
        (14_000, ""), // long loaf so roaming gets stage time
    ];
    std::thread::Builder::new()
        .name("fabric-companion-demo".into())
        .spawn(move || {
            let bound = BridgeUpdate::Bound {
                session_id: "demo".into(),
                running: false,
            };
            if tx.send(bound).is_err() {
                return;
            }
            loop {
                for &(delay_ms, event_type) in SCRIPT {
                    std::thread::sleep(Duration::from_millis(delay_ms));
                    if event_type.is_empty() {
                        continue;
                    }
                    let payload = if event_type == "clarify.request" {
                        serde_json::json!({"request_id": "demo", "question": "which way?"})
                    } else {
                        serde_json::Value::Null
                    };
                    let event = Event {
                        event_type: event_type.to_owned(),
                        session_id: String::new(),
                        payload,
                    };
                    if tx.send(BridgeUpdate::Event(event)).is_err() {
                        return;
                    }
                }
            }
        })
        .expect("spawn demo feed thread");
}

/// (row name, row index, frame count) — mirrors `ROW_SPECS`.
const ROW_SPECS: &[(&str, u32, u32)] = &[
    ("idle", 0, 6),
    ("running-right", 1, 8),
    ("running-left", 2, 8),
    ("waving", 3, 4),
    ("jumping", 4, 5),
    ("failed", 5, 8),
    ("waiting", 6, 6),
    ("running", 7, 6),
    ("review", 8, 6),
];

/// Fabric brand primary (#7C66E1) and highlight (#9481E6).
const BODY: Rgba<u8> = Rgba([0x7C, 0x66, 0xE1, 0xFF]);
const BODY_LIGHT: Rgba<u8> = Rgba([0x94, 0x81, 0xE6, 0xFF]);
const INK: Rgba<u8> = Rgba([0x19, 0x29, 0x4D, 0xFF]);
const WHITE: Rgba<u8> = Rgba([0xF0, 0xED, 0xFB, 0xFF]);

/// Cells are drawn on a quarter-resolution grid then upscaled ×4
/// nearest-neighbor for a chunky pixel-art look.
const GRID_W: u32 = FRAME_W / 4; // 48
const GRID_H: u32 = FRAME_H / 4; // 52

pub fn demo_spritesheet() -> RgbaImage {
    let mut sheet = RgbaImage::new(FRAME_W * 8, FRAME_H * 9);
    for &(name, row, count) in ROW_SPECS {
        for frame in 0..count {
            let cell = draw_cell(name, frame, count);
            blit_scaled(&mut sheet, &cell, frame * FRAME_W, row * FRAME_H);
        }
    }
    sheet
}

fn blit_scaled(sheet: &mut RgbaImage, cell: &RgbaImage, dx: u32, dy: u32) {
    for y in 0..cell.height() {
        for x in 0..cell.width() {
            let px = *cell.get_pixel(x, y);
            if px.0[3] == 0 {
                continue;
            }
            for sy in 0..4 {
                for sx in 0..4 {
                    sheet.put_pixel(dx + x * 4 + sx, dy + y * 4 + sy, px);
                }
            }
        }
    }
}

fn fill_ellipse(img: &mut RgbaImage, cx: f32, cy: f32, rx: f32, ry: f32, color: Rgba<u8>) {
    for y in 0..img.height() {
        for x in 0..img.width() {
            let (dx, dy) = ((x as f32 - cx) / rx, (y as f32 - cy) / ry);
            if dx * dx + dy * dy <= 1.0 {
                img.put_pixel(x, y, color);
            }
        }
    }
}

fn put(img: &mut RgbaImage, x: i32, y: i32, color: Rgba<u8>) {
    if x >= 0 && y >= 0 && (x as u32) < img.width() && (y as u32) < img.height() {
        img.put_pixel(x as u32, y as u32, color);
    }
}

fn dot(img: &mut RgbaImage, x: i32, y: i32, color: Rgba<u8>) {
    for oy in 0..2 {
        for ox in 0..2 {
            put(img, x + ox, y + oy, color);
        }
    }
}

/// A blob with eyes: squash/stretch, vertical offset, and eye placement give
/// each state its own silhouette and motion.
struct Blob {
    dy: f32,
    squash: f32, // >1 = wider+flatter, <1 = taller+narrower
    eye_dx: f32, // eyes look toward travel/attention
    eye_dy: f32,
    blink: bool,
    cross_eyes: bool, // failed
}

fn draw_blob(img: &mut RgbaImage, blob: &Blob) {
    let (cx, base_cy) = (GRID_W as f32 / 2.0, GRID_H as f32 - 16.0);
    let cy = base_cy + blob.dy;
    let (rx, ry) = (13.0 * blob.squash, 12.0 / blob.squash);
    fill_ellipse(img, cx, cy, rx, ry, BODY);
    // Top highlight for a little volume.
    fill_ellipse(
        img,
        cx - rx * 0.25,
        cy - ry * 0.45,
        rx * 0.45,
        ry * 0.3,
        BODY_LIGHT,
    );

    let (ex, ey) = (cx + blob.eye_dx, cy - ry * 0.25 + blob.eye_dy);
    for side in [-1.0f32, 1.0] {
        let x = (ex + side * rx * 0.35) as i32;
        let y = ey as i32;
        if blob.cross_eyes {
            put(img, x - 1, y - 1, INK);
            put(img, x + 1, y - 1, INK);
            put(img, x, y, INK);
            put(img, x - 1, y + 1, INK);
            put(img, x + 1, y + 1, INK);
        } else if blob.blink {
            put(img, x - 1, y, INK);
            put(img, x, y, INK);
            put(img, x + 1, y, INK);
        } else {
            dot(img, x, y, INK);
            put(img, x, y, WHITE); // glint
        }
    }
}

fn draw_cell(name: &str, frame: u32, count: u32) -> RgbaImage {
    let mut img = RgbaImage::new(GRID_W, GRID_H);
    let t = frame as f32 / count as f32;
    let cycle = (t * 2.0 * PI).sin();
    match name {
        "idle" => draw_blob(
            &mut img,
            &Blob {
                dy: cycle.round(),
                squash: 1.0 + 0.03 * cycle,
                eye_dx: 0.0,
                eye_dy: 0.0,
                blink: frame == count - 1,
                cross_eyes: false,
            },
        ),
        "running-right" | "running-left" | "running" => {
            let facing = match name {
                "running-right" => 1.0,
                "running-left" => -1.0,
                _ => 0.0,
            };
            let bounce = (t * 2.0 * PI * 2.0).sin().abs();
            draw_blob(
                &mut img,
                &Blob {
                    dy: -3.0 * bounce,
                    squash: 1.0 + 0.12 * (1.0 - bounce),
                    eye_dx: 3.0 * facing,
                    eye_dy: 0.0,
                    blink: false,
                    cross_eyes: false,
                },
            );
        }
        "waving" => {
            draw_blob(
                &mut img,
                &Blob {
                    dy: 0.0,
                    squash: 1.0,
                    eye_dx: 0.0,
                    eye_dy: -1.0,
                    blink: false,
                    cross_eyes: false,
                },
            );
            // A little arm arcing overhead.
            let angle = PI * (0.25 + 0.5 * t);
            let (ax, ay) = (
                GRID_W as f32 / 2.0 + 15.0 * angle.cos(),
                GRID_H as f32 - 16.0 - 14.0 * angle.sin(),
            );
            fill_ellipse(&mut img, ax, ay, 3.0, 3.0, BODY_LIGHT);
        }
        "jumping" => {
            let arc = (t * PI).sin();
            draw_blob(
                &mut img,
                &Blob {
                    dy: -10.0 * arc,
                    squash: if frame == 0 { 1.2 } else { 1.0 - 0.15 * arc },
                    eye_dx: 0.0,
                    eye_dy: -1.0,
                    blink: false,
                    cross_eyes: false,
                },
            );
        }
        "failed" => draw_blob(
            &mut img,
            &Blob {
                dy: 4.0,
                squash: 1.35 + 0.02 * cycle,
                eye_dx: 0.0,
                eye_dy: 1.0,
                blink: false,
                cross_eyes: true,
            },
        ),
        "waiting" => {
            draw_blob(
                &mut img,
                &Blob {
                    dy: 0.0,
                    squash: 1.0,
                    eye_dx: 0.0,
                    eye_dy: -2.0,
                    blink: frame == count - 1,
                    cross_eyes: false,
                },
            );
            // Bobbing attention dot overhead.
            let y = 8.0 + 1.5 * cycle;
            fill_ellipse(&mut img, GRID_W as f32 / 2.0, y, 2.0, 2.0, BODY_LIGHT);
        }
        "review" => {
            // Eyes scan across the row of frames.
            let scan = -3.0 + 6.0 * t;
            draw_blob(
                &mut img,
                &Blob {
                    dy: 0.0,
                    squash: 1.0,
                    eye_dx: scan,
                    eye_dy: 0.0,
                    blink: false,
                    cross_eyes: false,
                },
            );
        }
        _ => draw_blob(
            &mut img,
            &Blob {
                dy: 0.0,
                squash: 1.0,
                eye_dx: 0.0,
                eye_dy: 0.0,
                blink: false,
                cross_eyes: false,
            },
        ),
    }
    img
}

#[cfg(test)]
mod tests {
    use super::*;
    use fabric_companion_core::atlas::{state_frame_count, AtlasGrid};
    use fabric_companion_core::state::PetState;

    #[test]
    fn demo_sheet_matches_the_codex_contract() {
        let sheet = demo_spritesheet();
        assert_eq!((sheet.width(), sheet.height()), (1536, 1872));
        let grid = AtlasGrid::from_dimensions(sheet.width(), sheet.height());
        assert_eq!((grid.cols, grid.rows), (8, 9));
        // Blank-trim sees the intended per-state counts (capped at 6).
        assert_eq!(state_frame_count(&sheet, PetState::Idle), 6);
        assert_eq!(state_frame_count(&sheet, PetState::Wave), 4);
        assert_eq!(state_frame_count(&sheet, PetState::Jump), 5);
        assert_eq!(state_frame_count(&sheet, PetState::Failed), 6);
        assert_eq!(state_frame_count(&sheet, PetState::Waiting), 6);
        assert_eq!(state_frame_count(&sheet, PetState::Run), 6);
        assert_eq!(state_frame_count(&sheet, PetState::Review), 6);
    }
}
