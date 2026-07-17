//! Read-only access to the on-disk pet store and pet display settings.
//!
//! Rust mirror of the read paths in `agent/pet/store.py` plus the
//! `get_fabric_home()` resolution from `fabric_constants.py` and the
//! `display.pet.*` block of `<FABRIC_HOME>/config.yaml`. The companion never
//! writes any of these files — installing, renaming, and selecting pets stays
//! with `fabric pets ...` and the other surfaces; this overlay just renders
//! whatever they configured.
//!
//! Layout consumed:
//!
//! ```text
//! <FABRIC_HOME>/pets/<slug>/pet.json
//! <FABRIC_HOME>/pets/<slug>/spritesheet.webp   (or .png, or sprite.{webp,png})
//! <FABRIC_HOME>/config.yaml                    (display.pet.* block)
//! ```

use std::path::{Path, PathBuf};

use serde_json::Value as JsonValue;
use serde_yaml::Value as YamlValue;

use crate::atlas::{clamp_scale, DEFAULT_SCALE};

/// Resolve the fabric state directory, mirroring `get_fabric_home()`:
///
/// 1. env `FABRIC_HOME`, then env `HERMES_HOME` (non-empty, stripped)
/// 2. legacy compat: the old `hermes` directory if it exists and the new
///    `fabric` one does not
/// 3. platform default: `~/.fabric` on POSIX, `%LOCALAPPDATA%\fabric` on
///    Windows
pub fn fabric_home() -> PathBuf {
    // public-release-audit: allow-legacy-compat -- FABRIC_HOME first, then the pre-rename env var for one transition window (mirrors fabric_constants.get_fabric_home)
    for var in ["FABRIC_HOME", "HERMES_HOME"] {
        if let Ok(raw) = std::env::var(var) {
            let trimmed = raw.trim();
            if !trimmed.is_empty() {
                return PathBuf::from(trimmed);
            }
        }
    }
    let (fabric, hermes) = default_home_candidates();
    if hermes.exists() && !fabric.exists() {
        hermes
    } else {
        fabric
    }
}

#[cfg(windows)]
fn default_home_candidates() -> (PathBuf, PathBuf) {
    // Canonical order (get_fabric_home): the %LOCALAPPDATA% environment
    // variable first, then the known-folder/home fallbacks.
    let base = std::env::var("LOCALAPPDATA")
        .ok()
        .map(|v| v.trim().to_owned())
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .or_else(dirs::data_local_dir)
        .or_else(|| dirs::home_dir().map(|h| h.join("AppData").join("Local")))
        .unwrap_or_else(|| PathBuf::from("."));
    // public-release-audit: allow-legacy-compat -- pre-rename state dir consulted read-only during the migration window
    (base.join("fabric"), base.join("hermes"))
}

#[cfg(not(windows))]
fn default_home_candidates() -> (PathBuf, PathBuf) {
    let home = dirs::home_dir().unwrap_or_else(|| PathBuf::from("."));
    // public-release-audit: allow-legacy-compat -- pre-rename state dir consulted read-only during the migration window
    (home.join(".fabric"), home.join(".hermes"))
}

/// The pet store directory under *home* (not created — read-only access).
pub fn pets_dir(home: &Path) -> PathBuf {
    home.join("pets")
}

/// Sanitize an externally-supplied slug, mirroring `_safe_slug`: keep only
/// the final path component so a slug carrying separators (`pets/boba`,
/// `../x`, absolute paths) can never escape the pets directory, and reject
/// empty / `.` / `..` results outright.
fn safe_slug(slug: &str) -> Option<&str> {
    let name = Path::new(slug.trim()).file_name()?.to_str()?;
    if name.is_empty() || name == "." || name == ".." {
        return None;
    }
    Some(name)
}

/// One installed pet, resolved from `pets/<slug>/`.
#[derive(Debug, Clone, PartialEq)]
pub struct InstalledPet {
    pub slug: String,
    pub display_name: String,
    pub description: String,
    /// Resolved spritesheet path; guaranteed to exist for pets returned by
    /// [`installed_pets`] / [`resolve_active_pet`].
    pub spritesheet: PathBuf,
    /// True for locally hatched pets (`"createdBy": "generator"`).
    pub generated: bool,
    /// The full `pet.json` document. Upstream petdex documents may carry keys
    /// beyond the ones parsed above; keep the raw value so nothing is lost.
    pub meta: JsonValue,
}

/// Read `pet.json`, tolerating a missing or unreadable file (`{}` fallback —
/// the pet still loads with its slug as the name, like the Python store).
fn read_pet_meta(dir: &Path) -> JsonValue {
    std::fs::read_to_string(dir.join("pet.json"))
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .filter(JsonValue::is_object)
        .unwrap_or_else(|| JsonValue::Object(Default::default()))
}

/// Resolve the spritesheet file for a pet dir: honor `spritesheetPath` when
/// it names an existing file, else probe the well-known names. Returns None
/// when nothing exists (the Python store's "stable default path" only
/// matters for writers).
fn resolve_spritesheet(dir: &Path, meta: &JsonValue) -> Option<PathBuf> {
    if let Some(rel) = meta.get("spritesheetPath").and_then(JsonValue::as_str) {
        if !rel.is_empty() {
            let candidate = dir.join(rel);
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    for name in [
        "spritesheet.webp",
        "spritesheet.png",
        "sprite.webp",
        "sprite.png",
    ] {
        let candidate = dir.join(name);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

fn load_pet(dir: &Path, slug: &str) -> Option<InstalledPet> {
    let meta = read_pet_meta(dir);
    let spritesheet = resolve_spritesheet(dir, &meta)?;
    let text = |key: &str| -> Option<String> {
        meta.get(key)
            .and_then(JsonValue::as_str)
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
    };
    Some(InstalledPet {
        slug: slug.to_owned(),
        display_name: text("displayName").unwrap_or_else(|| slug.to_owned()),
        description: text("description").unwrap_or_default(),
        spritesheet,
        generated: meta.get("createdBy").and_then(JsonValue::as_str) == Some("generator"),
        meta,
    })
}

/// All pets installed under *home*, sorted by slug. Only directories whose
/// resolved spritesheet file exists are included.
pub fn installed_pets(home: &Path) -> Vec<InstalledPet> {
    let mut slugs: Vec<String> = std::fs::read_dir(pets_dir(home))
        .into_iter()
        .flatten()
        .flatten()
        .filter(|entry| entry.path().is_dir())
        .filter_map(|entry| entry.file_name().into_string().ok())
        .filter(|name| !name.starts_with('.'))
        .collect();
    slugs.sort();
    slugs
        .into_iter()
        .filter_map(|slug| load_pet(&pets_dir(home).join(&slug), &slug))
        .collect()
}

/// The pet the companion should show: the configured slug when it is
/// installed with an existing spritesheet, else the first installed pet
/// alphabetically, else None. Mirrors `resolve_active_pet`.
pub fn resolve_active_pet(home: &Path, configured_slug: &str) -> Option<InstalledPet> {
    if let Some(slug) = safe_slug(configured_slug) {
        if let Some(pet) = load_pet(&pets_dir(home).join(slug), slug) {
            return Some(pet);
        }
    }
    installed_pets(home).into_iter().next()
}

/// The `display.pet.*` block of `config.yaml`, with the same defaults the
/// Python `DEFAULT_CONFIG` applies (`save_config` strips default-valued keys,
/// so an absent key *means* the default).
#[derive(Debug, Clone, PartialEq)]
pub struct PetDisplayConfig {
    pub enabled: bool,
    pub slug: String,
    pub render_mode: String,
    pub scale: f32,
    pub unicode_cols: u32,
}

impl Default for PetDisplayConfig {
    fn default() -> Self {
        PetDisplayConfig {
            enabled: false,
            slug: String::new(),
            render_mode: "auto".to_owned(),
            scale: DEFAULT_SCALE,
            unicode_cols: 0,
        }
    }
}

impl PetDisplayConfig {
    /// The scale to render at, clamped to the sanctioned range (writers clamp
    /// on save, but the file is hand-editable).
    pub fn effective_scale(&self) -> f32 {
        clamp_scale(if self.scale > 0.0 {
            self.scale
        } else {
            DEFAULT_SCALE
        })
    }
}

/// Read `display.pet.*` from `<home>/config.yaml`. Missing file, unparseable
/// YAML, missing keys, or wrong-typed values all fall back to defaults — the
/// same isinstance-guarded tolerance the Python readers apply.
pub fn load_pet_config(home: &Path) -> PetDisplayConfig {
    let Some(root) = std::fs::read_to_string(home.join("config.yaml"))
        .ok()
        .and_then(|text| serde_yaml::from_str::<YamlValue>(&text).ok())
    else {
        return PetDisplayConfig::default();
    };
    let pet = root
        .get("display")
        .and_then(|display| display.get("pet"))
        .cloned()
        .unwrap_or(YamlValue::Null);

    let mut config = PetDisplayConfig::default();
    if let Some(enabled) = pet.get("enabled").and_then(YamlValue::as_bool) {
        config.enabled = enabled;
    }
    if let Some(slug) = pet.get("slug").and_then(YamlValue::as_str) {
        config.slug = slug.to_owned();
    }
    if let Some(mode) = pet.get("render_mode").and_then(YamlValue::as_str) {
        config.render_mode = mode.to_owned();
    }
    if let Some(scale) = pet.get("scale").and_then(YamlValue::as_f64) {
        config.scale = scale as f32;
    }
    if let Some(cols) = pet.get("unicode_cols").and_then(YamlValue::as_u64) {
        config.unicode_cols = cols as u32;
    }
    config
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write(path: &Path, contents: &str) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, contents).unwrap();
    }

    fn install_fake_pet(home: &Path, slug: &str, meta: &str, sheet_name: &str) {
        let dir = pets_dir(home).join(slug);
        write(&dir.join("pet.json"), meta);
        write(&dir.join(sheet_name), "not-a-real-image");
    }

    #[test]
    fn lists_pets_sorted_and_skips_sheetless_dirs() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        install_fake_pet(
            home,
            "zebra",
            r#"{"displayName": "Zebra"}"#,
            "spritesheet.webp",
        );
        install_fake_pet(home, "axolotl", "{}", "spritesheet.png");
        // Directory without any spritesheet — must be skipped.
        write(&pets_dir(home).join("ghost").join("pet.json"), "{}");
        // Dotted dirs (.thumbs cache) must be skipped.
        write(&pets_dir(home).join(".thumbs").join("zebra.png"), "");

        let pets = installed_pets(home);
        let slugs: Vec<_> = pets.iter().map(|p| p.slug.as_str()).collect();
        assert_eq!(slugs, ["axolotl", "zebra"]);
        assert_eq!(pets[1].display_name, "Zebra");
        assert_eq!(pets[0].display_name, "axolotl"); // slug fallback
    }

    #[test]
    fn honors_spritesheet_path_then_probes() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        install_fake_pet(
            home,
            "custom",
            r#"{"spritesheetPath": "art.webp"}"#,
            "art.webp",
        );
        let pet = resolve_active_pet(home, "custom").unwrap();
        assert!(pet.spritesheet.ends_with("art.webp"));

        // spritesheetPath pointing at a missing file falls back to probing.
        install_fake_pet(
            home,
            "stale",
            r#"{"spritesheetPath": "gone.webp"}"#,
            "sprite.png",
        );
        let pet = resolve_active_pet(home, "stale").unwrap();
        assert!(pet.spritesheet.ends_with("sprite.png"));
    }

    #[test]
    fn active_pet_falls_back_to_first_installed() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        assert_eq!(resolve_active_pet(home, ""), None);
        install_fake_pet(home, "beta", "{}", "spritesheet.webp");
        install_fake_pet(home, "alpha", "{}", "spritesheet.webp");
        assert_eq!(resolve_active_pet(home, "").unwrap().slug, "alpha");
        assert_eq!(resolve_active_pet(home, "beta").unwrap().slug, "beta");
        assert_eq!(resolve_active_pet(home, "missing").unwrap().slug, "alpha");
    }

    #[test]
    fn generated_flag_and_meta_round_trip() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        install_fake_pet(
            home,
            "hatchling",
            r#"{"createdBy": "generator", "futureKey": {"nested": true}}"#,
            "spritesheet.webp",
        );
        let pet = resolve_active_pet(home, "hatchling").unwrap();
        assert!(pet.generated);
        assert_eq!(pet.meta["futureKey"]["nested"], JsonValue::Bool(true));
    }

    #[test]
    fn corrupt_pet_json_still_loads() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        install_fake_pet(home, "broken", "{ not json", "spritesheet.webp");
        let pet = resolve_active_pet(home, "broken").unwrap();
        assert_eq!(pet.display_name, "broken");
        assert!(!pet.generated);
    }

    #[test]
    fn pet_config_defaults_and_overrides() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        assert_eq!(load_pet_config(home), PetDisplayConfig::default());

        write(
            &home.join("config.yaml"),
            "display:\n  pet:\n    enabled: true\n    slug: axolotl\n    scale: 0.5\n",
        );
        let config = load_pet_config(home);
        assert!(config.enabled);
        assert_eq!(config.slug, "axolotl");
        assert_eq!(config.scale, 0.5);
        assert_eq!(config.render_mode, "auto"); // absent → default
        assert_eq!(config.unicode_cols, 0);
    }

    #[test]
    fn pet_config_tolerates_junk() {
        let tmp = tempfile::tempdir().unwrap();
        let home = tmp.path();
        write(&home.join("config.yaml"), "display: 42\n");
        assert_eq!(load_pet_config(home), PetDisplayConfig::default());
        write(&home.join("config.yaml"), ":: not yaml ::{{{\n");
        assert_eq!(load_pet_config(home), PetDisplayConfig::default());
        write(
            &home.join("config.yaml"),
            "display:\n  pet:\n    enabled: \"yes\"\n    scale: huge\n",
        );
        assert_eq!(load_pet_config(home), PetDisplayConfig::default());
    }

    #[test]
    fn effective_scale_clamps_hand_edits() {
        let mut config = PetDisplayConfig::default();
        config.scale = 50.0;
        assert_eq!(config.effective_scale(), 3.0);
        config.scale = 0.0;
        assert_eq!(config.effective_scale(), DEFAULT_SCALE);
    }
}
