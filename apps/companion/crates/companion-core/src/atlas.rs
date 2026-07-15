//! Petdex spritesheet geometry, row taxonomy, and frame extraction.
//!
//! Rust mirror of `agent/pet/constants.py` (geometry + taxonomy) and the
//! display-path pieces of `agent/pet/render.py` (`_raw_frames`,
//! `state_frame_counts`). Two atlas shapes exist in the wild:
//!
//! - Current petdex/Codex sheets: 1536×1872 px — 8 columns × 9 rows.
//! - Legacy Hermes/petdex sheets: 1728×1664 px — 9 columns × 8 rows.
//!
//! Nothing checks exact sizes at display time; renderers floor-divide the
//! concrete sheet into cells and pick the taxonomy from the row count, so
//! either shape (or an odd-sized sheet) degrades gracefully.

use image::RgbaImage;

use crate::state::PetState;

/// Atlas cell width, pixels.
pub const FRAME_W: u32 = 192;
/// Atlas cell height, pixels.
pub const FRAME_H: u32 = 208;

/// Frames stepped through per animation state, even if the sheet's row has
/// more columns (the petdex web app uses CSS `steps(6)`).
pub const FRAMES_PER_STATE: u32 = 6;

/// Full-loop duration for one state, milliseconds (petdex default).
pub const LOOP_MS: u32 = 1100;

/// Default on-screen scale relative to native frame size (`display.pet.scale`).
pub const DEFAULT_SCALE: f32 = 0.33;
/// User-settable scale floor (keeps the pet clickable/visible).
pub const MIN_SCALE: f32 = 0.1;
/// User-settable scale ceiling (stops a fat-fingered value filling the screen).
pub const MAX_SCALE: f32 = 3.0;

/// A frame is "blank" when its max alpha is at or below this (display path;
/// generation-side segmentation uses different thresholds on purpose).
pub const BLANK_ALPHA: u8 = 8;

/// Clamp *scale* to `[MIN_SCALE, MAX_SCALE]` (the single validation point).
pub fn clamp_scale(scale: f32) -> f32 {
    scale.clamp(MIN_SCALE, MAX_SCALE)
}

/// Legacy Hermes/petdex row order (top → bottom) for 8-row atlases.
pub const LEGACY_STATE_ROWS: &[&str] = &[
    "idle", "wave", "run", "failed", "review", "jump", "extra1", "extra2",
];

/// Current petdex/Codex row order (top → bottom) for 9-row atlases.
///
/// `running` (row 7) is the working-in-place animation the driven states use;
/// `running-right` / `running-left` (rows 1/2) are directional walk cycles
/// reserved for roaming.
pub const CODEX_STATE_ROWS: &[&str] = &[
    "idle",
    "running-right",
    "running-left",
    "waving",
    "jumping",
    "failed",
    "waiting",
    "running",
    "review",
];

/// Canonical activity names → accepted row-name aliases in descending
/// preference. Keeps internal state names stable (`wave`/`jump`/`run`) while
/// matching petdex's current `waving`/`jumping`/`running` taxonomy.
pub fn state_aliases_for(state: PetState) -> &'static [&'static str] {
    match state {
        PetState::Idle => &["idle"],
        PetState::Wave => &["wave", "waving"],
        PetState::Jump => &["jump", "jumping"],
        PetState::Run => &["run", "running"],
        PetState::Failed => &["failed"],
        PetState::Review => &["review"],
        PetState::Waiting => &["waiting"],
    }
}

/// Pick the row taxonomy for a sheet with *rows* concrete rows: 9+ rows is the
/// current Codex shape, anything smaller (including unknown shapes) is legacy.
pub fn state_rows_for_grid(rows: u32) -> &'static [&'static str] {
    if rows as usize >= CODEX_STATE_ROWS.len() {
        CODEX_STATE_ROWS
    } else {
        LEGACY_STATE_ROWS
    }
}

/// Resolve *state* to a row index within the taxonomy for *rows* concrete
/// rows: first alias that appears in the row list wins; unknown states fall
/// back to row 0 (idle). Never fails — mirrors `state_row_index`.
pub fn state_row_index(state: PetState, rows: u32) -> u32 {
    let row_names = state_rows_for_grid(rows);
    for alias in state_aliases_for(state) {
        if let Some(idx) = row_names.iter().position(|name| name == alias) {
            return idx as u32;
        }
    }
    0
}

/// Concrete cell grid of a spritesheet, floor-divided from pixel dimensions.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AtlasGrid {
    pub width: u32,
    pub height: u32,
    pub cols: u32,
    pub rows: u32,
}

impl AtlasGrid {
    pub fn from_dimensions(width: u32, height: u32) -> Self {
        AtlasGrid {
            width,
            height,
            cols: (width / FRAME_W).max(1),
            rows: (height / FRAME_H).max(1),
        }
    }

    /// Pixel Y of the top of *row*, clamped so a full `FRAME_H` cell always
    /// fits — some pets ship fewer physical rows than the taxonomy names.
    pub fn row_top(&self, row: u32) -> u32 {
        let top = row * FRAME_H;
        if top + FRAME_H > self.height {
            self.height.saturating_sub(FRAME_H)
        } else {
            top
        }
    }

    /// Row index for *state* under this grid's taxonomy.
    pub fn row_for_state(&self, state: PetState) -> u32 {
        state_row_index(state, self.rows)
    }

    /// Frames available to step through in one row: capped by
    /// [`FRAMES_PER_STATE`] and the sheet's physical column count.
    pub fn max_frames(&self) -> u32 {
        FRAMES_PER_STATE.min(self.cols)
    }
}

/// A sprite row choice with a horizontal mirror flag (art convention: pets
/// face left; mirroring turns a left-facing row into rightward travel).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WalkRow {
    pub row: u32,
    pub mirror: bool,
}

/// Pick the locomotion row for horizontal travel direction *dir* (±1),
/// mirroring the Electron `roamWalkRow`: prefer the dedicated directional
/// rows Codex sheets ship (`running-right` / `running-left`), fall back to
/// mirroring the opposite one, and finally to the plain [`PetState::Run`]
/// row (mirrored for rightward travel). `dir == 0` means at rest — no
/// locomotion row; callers apply the resting-facing rule instead.
pub fn roam_walk_row(grid: &AtlasGrid, dir: i8) -> Option<WalkRow> {
    if dir == 0 {
        return None;
    }
    let rows = state_rows_for_grid(grid.rows);
    let find = |name: &str| rows.iter().position(|n| *n == name).map(|i| i as u32);
    let (preferred, fallback) = if dir > 0 {
        ("running-right", "running-left")
    } else {
        ("running-left", "running-right")
    };
    if let Some(row) = find(preferred) {
        return Some(WalkRow { row, mirror: false });
    }
    if let Some(row) = find(fallback) {
        return Some(WalkRow { row, mirror: true });
    }
    Some(WalkRow {
        row: grid.row_for_state(PetState::Run),
        mirror: dir > 0,
    })
}

/// True when the `FRAME_W`×`FRAME_H` cell at (*col*, *top_px*) is blank —
/// max alpha at or below [`BLANK_ALPHA`]. Cells that extend past the image
/// edge count the in-bounds pixels only.
fn cell_is_blank(sheet: &RgbaImage, col: u32, top_px: u32) -> bool {
    let left = col * FRAME_W;
    let right = (left + FRAME_W).min(sheet.width());
    let bottom = (top_px + FRAME_H).min(sheet.height());
    for y in top_px..bottom {
        for x in left..right {
            if sheet.get_pixel(x, y).0[3] > BLANK_ALPHA {
                return false;
            }
        }
    }
    true
}

/// Count the animation frames in concrete *row*: walk the row's cells left
/// to right, stopping at the first blank cell (sheets are left-packed;
/// trailing columns of a short row are fully transparent padding). Mirrors
/// `_raw_frames` in `agent/pet/render.py`.
///
/// Returns 0 when even the first cell is blank; callers should treat that as
/// "row has no art" and fall back to the idle row rather than divide by zero
/// when pacing the loop.
pub fn row_frame_count(sheet: &RgbaImage, row: u32) -> u32 {
    let grid = AtlasGrid::from_dimensions(sheet.width(), sheet.height());
    let top = grid.row_top(row);
    let mut count = 0;
    for col in 0..grid.max_frames() {
        if col * FRAME_W >= sheet.width() || cell_is_blank(sheet, col, top) {
            break;
        }
        count += 1;
    }
    count
}

/// [`row_frame_count`] for the row *state* resolves to. Mirrors
/// `state_frame_counts` in `agent/pet/render.py`.
pub fn state_frame_count(sheet: &RgbaImage, state: PetState) -> u32 {
    let grid = AtlasGrid::from_dimensions(sheet.width(), sheet.height());
    row_frame_count(sheet, grid.row_for_state(state))
}

/// Per-state frame counts for a whole sheet (what the gateway ships to the
/// desktop canvas; the companion computes it locally).
pub fn state_frame_counts(sheet: &RgbaImage) -> Vec<(PetState, u32)> {
    [
        PetState::Idle,
        PetState::Wave,
        PetState::Run,
        PetState::Failed,
        PetState::Review,
        PetState::Jump,
        PetState::Waiting,
    ]
    .into_iter()
    .map(|s| (s, state_frame_count(sheet, s)))
    .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::Rgba;

    /// Paint a synthetic sheet: `frames[row]` opaque cells per row, rest blank.
    fn synthetic_sheet(cols: u32, frames: &[u32]) -> RgbaImage {
        let rows = frames.len() as u32;
        let mut img = RgbaImage::new(cols * FRAME_W, rows * FRAME_H);
        for (row, &n) in frames.iter().enumerate() {
            for col in 0..n.min(cols) {
                let (x, y) = (
                    col * FRAME_W + FRAME_W / 2,
                    row as u32 * FRAME_H + FRAME_H / 2,
                );
                img.put_pixel(x, y, Rgba([255, 255, 255, 255]));
            }
        }
        img
    }

    #[test]
    fn codex_shape_selects_codex_taxonomy() {
        let grid = AtlasGrid::from_dimensions(1536, 1872);
        assert_eq!((grid.cols, grid.rows), (8, 9));
        assert_eq!(grid.row_for_state(PetState::Wave), 3); // "waving"
        assert_eq!(grid.row_for_state(PetState::Jump), 4); // "jumping"
        assert_eq!(grid.row_for_state(PetState::Run), 7); // "running" (in place)
        assert_eq!(grid.row_for_state(PetState::Waiting), 6);
        assert_eq!(grid.row_for_state(PetState::Review), 8);
    }

    #[test]
    fn legacy_shape_selects_legacy_taxonomy() {
        let grid = AtlasGrid::from_dimensions(1728, 1664);
        assert_eq!((grid.cols, grid.rows), (9, 8));
        assert_eq!(grid.row_for_state(PetState::Wave), 1);
        assert_eq!(grid.row_for_state(PetState::Run), 2);
        // Legacy sheets have no waiting row — falls back to idle (row 0).
        assert_eq!(grid.row_for_state(PetState::Waiting), 0);
    }

    #[test]
    fn odd_shapes_degrade_gracefully() {
        // Smaller than one cell still yields a 1x1 grid (legacy taxonomy).
        let grid = AtlasGrid::from_dimensions(100, 100);
        assert_eq!((grid.cols, grid.rows), (1, 1));
        assert_eq!(grid.row_top(5), 0); // clamped — cell taller than sheet
        assert_eq!(grid.max_frames(), 1);
    }

    #[test]
    fn row_top_clamps_to_sheet_bottom() {
        // 9-row taxonomy but only 2 physical rows of pixels.
        let grid = AtlasGrid::from_dimensions(1536, 2 * FRAME_H);
        assert_eq!(grid.row_top(1), FRAME_H);
        assert_eq!(grid.row_top(8), FRAME_H); // clamped to last full cell
    }

    #[test]
    fn blank_trim_counts_left_packed_frames() {
        // Codex-shaped synthetic sheet with per-row frame counts akin to
        // generate/atlas.py ROW_SPECS (capped at 8 cols).
        let frames = [6, 8, 8, 4, 5, 8, 6, 6, 6];
        let sheet = synthetic_sheet(8, &frames);
        assert_eq!(state_frame_count(&sheet, PetState::Idle), 6);
        assert_eq!(state_frame_count(&sheet, PetState::Wave), 4); // "waving" row
        assert_eq!(state_frame_count(&sheet, PetState::Jump), 5); // "jumping" row
                                                                  // 8-frame rows are capped by FRAMES_PER_STATE.
        assert_eq!(state_frame_count(&sheet, PetState::Failed), 6);
    }

    #[test]
    fn fully_blank_row_counts_zero() {
        let frames = [6, 0, 0, 0, 0, 0, 0, 0, 0];
        let sheet = synthetic_sheet(8, &frames);
        assert_eq!(state_frame_count(&sheet, PetState::Failed), 0);
        assert_eq!(state_frame_count(&sheet, PetState::Idle), 6);
    }

    #[test]
    fn faint_alpha_is_still_blank() {
        let mut sheet = RgbaImage::new(FRAME_W * 8, FRAME_H * 9);
        sheet.put_pixel(0, 0, Rgba([255, 255, 255, BLANK_ALPHA]));
        assert_eq!(state_frame_count(&sheet, PetState::Idle), 0);
        sheet.put_pixel(0, 0, Rgba([255, 255, 255, BLANK_ALPHA + 1]));
        assert_eq!(state_frame_count(&sheet, PetState::Idle), 1);
    }

    #[test]
    fn walk_rows_prefer_directional_art() {
        let codex = AtlasGrid::from_dimensions(1536, 1872);
        assert_eq!(
            roam_walk_row(&codex, 1),
            Some(WalkRow {
                row: 1,
                mirror: false
            })
        );
        assert_eq!(
            roam_walk_row(&codex, -1),
            Some(WalkRow {
                row: 2,
                mirror: false
            })
        );
        assert_eq!(roam_walk_row(&codex, 0), None);

        // Legacy sheets have no directional rows: fall back to the run row,
        // mirrored for rightward travel (art faces left by convention).
        let legacy = AtlasGrid::from_dimensions(1728, 1664);
        assert_eq!(
            roam_walk_row(&legacy, 1),
            Some(WalkRow {
                row: 2,
                mirror: true
            })
        );
        assert_eq!(
            roam_walk_row(&legacy, -1),
            Some(WalkRow {
                row: 2,
                mirror: false
            })
        );
    }

    #[test]
    fn scale_clamps() {
        assert_eq!(clamp_scale(0.0), MIN_SCALE);
        assert_eq!(clamp_scale(99.0), MAX_SCALE);
        assert_eq!(clamp_scale(0.33), 0.33);
    }
}
