//! fabric-companion — an always-on-top desktop pet for Fabric.
//!
//! Phase 1 of the companion overlay: a transparent, undecorated,
//! click-through window that renders the user's installed petdex pet (or a
//! procedural demo blob) and mirrors live agent activity from a Fabric
//! backend over the `/api/ws` JSON-RPC WebSocket — the same protocol the
//! Electron desktop app speaks. See `apps/companion/README.md` for the
//! roadmap (speech bubbles, approvals, chat, voice).

mod args;
mod backend;
mod bridge;
mod demo;
mod pet;

use bevy::asset::RenderAssetUsages;
use bevy::diagnostic::FrameCount;
use bevy::prelude::*;
#[cfg(any(target_os = "macos", target_os = "linux"))]
use bevy::window::CompositeAlphaMode;
use bevy::window::{CursorOptions, PrimaryWindow, WindowLevel};
use clap::Parser;
use fabric_companion_core::atlas::{clamp_scale, row_frame_count, AtlasGrid, FRAME_H, FRAME_W};
use fabric_companion_core::roam::FEET_DROP_PX;
use fabric_companion_core::store;
use image::RgbaImage;

use crate::args::Args;
use crate::bridge::{BridgeConfig, BridgeUpdate, SessionBinding};
use crate::pet::{Activity, Feed, PetPlugin, PetSpec, PetSpriteTag, Roam};

fn main() {
    let args = Args::parse();

    // ── Pet resolution: CLI flag → config.yaml → first installed → demo ──
    let home = store::fabric_home();
    let config = store::load_pet_config(&home);
    let scale = clamp_scale(args.scale.unwrap_or_else(|| config.effective_scale()));

    let configured_slug = args.pet.clone().unwrap_or_else(|| config.slug.clone());
    let (sheet, pet_name) = load_sheet(&home, &configured_slug, args.demo);
    let grid = AtlasGrid::from_dimensions(sheet.width(), sheet.height());
    let row_frames: Vec<u32> = (0..grid.rows).map(|r| row_frame_count(&sheet, r)).collect();

    // ── Feed: real backend bridge or the demo script ──
    let (tx, rx) = crossbeam_channel::unbounded::<BridgeUpdate>();
    let mut backend_guard = None;
    if args.wants_backend() {
        let url = if args.spawn {
            match backend::spawn_backend(&args.fabric_bin) {
                Ok((url, guard)) => {
                    backend_guard = Some(guard);
                    url
                }
                Err(err) => {
                    eprintln!("fabric-companion: {err}");
                    std::process::exit(1);
                }
            }
        } else {
            let base = args.url.clone().expect("clap guarantees --url here");
            match token_for(&args) {
                Some(token) => join_token(&base, &token),
                None => {
                    eprintln!("fabric-companion: --url needs --token (or $FABRIC_COMPANION_TOKEN)");
                    std::process::exit(1);
                }
            }
        };
        let binding = if let Some(sid) = args.session.clone() {
            SessionBinding::Resume(Some(sid))
        } else if args.resume_recent {
            SessionBinding::Resume(None)
        } else {
            SessionBinding::Create
        };
        bridge::spawn(
            BridgeConfig {
                url,
                binding,
                prompt: args.prompt.clone(),
            },
            tx,
        );
    } else {
        demo::spawn_demo_feed(tx);
    }

    // ── Window ──
    let position = match args.position.as_deref() {
        Some([x, y]) => WindowPosition::At(IVec2::new(*x, *y)),
        _ => WindowPosition::Automatic,
    };
    let pet_h = FRAME_H as f32 * scale;
    let floor_y = args.height as f32 - args.floor_offset;

    let mut window = Window {
        title: format!("Fabric Companion — {pet_name}"),
        transparent: !args.opaque,
        decorations: false,
        resizable: false,
        window_level: WindowLevel::AlwaysOnTop,
        resolution: (args.width, args.height).into(),
        position,
        skip_taskbar: true,
        // Spawn hidden; revealed after the first clean frames so the window
        // never flashes an opaque backdrop.
        visible: false,
        ..default()
    };
    // Transparency needs these blend modes off-Windows — but only when the
    // surface is actually transparent: requesting an alpha mode on an opaque
    // surface fails wgpu surface validation.
    if !args.opaque {
        #[cfg(target_os = "macos")]
        {
            window.composite_alpha_mode = CompositeAlphaMode::PostMultiplied;
        }
        #[cfg(target_os = "linux")]
        {
            window.composite_alpha_mode = CompositeAlphaMode::PreMultiplied;
        }
    }

    App::new()
        .add_plugins(
            DefaultPlugins
                .set(WindowPlugin {
                    primary_window: Some(window),
                    // Click-through by default: cursor input falls through to
                    // whatever is underneath (X11 doesn't support this — the
                    // overlay is interactive there regardless).
                    primary_cursor_options: Some(CursorOptions {
                        hit_test: args.interactive,
                        ..default()
                    }),
                    ..default()
                })
                .set(ImagePlugin::default_nearest()),
        )
        .insert_resource(ClearColor(if args.opaque {
            Color::srgb(0.098, 0.161, 0.302) // fabric status-bar navy #19294D
        } else {
            Color::NONE
        }))
        .insert_resource(PetSpec {
            grid,
            row_frames,
            scale,
        })
        .insert_resource(Feed(rx))
        .insert_resource(Activity::default())
        .insert_resource(Roam {
            enabled: !args.no_roam,
            floor_offset: args.floor_offset,
            roam_loop: None,
            position: Vec2::new(24.0, floor_y - pet_h + FEET_DROP_PX),
        })
        .insert_non_send(backend_guard)
        .add_plugins(PetPlugin)
        .add_systems(
            Startup,
            move |mut commands: Commands,
                  mut images: ResMut<Assets<Image>>,
                  mut layouts: ResMut<Assets<TextureAtlasLayout>>,
                  spec: Res<PetSpec>| {
                setup(&mut commands, &mut images, &mut layouts, &spec, &sheet);
            },
        )
        .add_systems(Update, reveal_window)
        .run();
}

fn load_sheet(home: &std::path::Path, slug: &str, force_demo: bool) -> (RgbaImage, String) {
    if !force_demo {
        if let Some(pet) = store::resolve_active_pet(home, slug) {
            match image::open(&pet.spritesheet) {
                Ok(img) => return (img.to_rgba8(), pet.display_name),
                Err(err) => {
                    eprintln!(
                        "fabric-companion: failed to decode {} ({err}); using the demo pet",
                        pet.spritesheet.display()
                    );
                }
            }
        }
    }
    (demo::demo_spritesheet(), "demo blob".to_owned())
}

fn token_for(args: &Args) -> Option<String> {
    args.token
        .clone()
        .or_else(|| std::env::var("FABRIC_COMPANION_TOKEN").ok())
        .filter(|t| !t.is_empty())
}

fn join_token(base: &str, token: &str) -> String {
    let sep = if base.contains('?') { '&' } else { '?' };
    format!("{base}{sep}token={token}")
}

fn setup(
    commands: &mut Commands,
    images: &mut Assets<Image>,
    layouts: &mut Assets<TextureAtlasLayout>,
    spec: &PetSpec,
    sheet: &RgbaImage,
) {
    commands.spawn(Camera2d);

    let image = images.add(rgba_to_bevy(sheet.clone()));
    let layout = layouts.add(TextureAtlasLayout::from_grid(
        UVec2::new(FRAME_W, FRAME_H),
        spec.grid.cols,
        spec.grid.rows,
        None,
        None,
    ));
    let shadow = images.add(rgba_to_bevy(shadow_image()));

    commands
        .spawn((
            PetSpriteTag::default(),
            Sprite::from_atlas_image(image, TextureAtlas { layout, index: 0 }),
            Transform::from_scale(Vec3::splat(spec.scale)),
        ))
        .with_children(|parent| {
            // Contact shadow under the feet (desktop parity: width 55% of the
            // pet, height 28% of that, alpha between the light/dark themes).
            parent.spawn((
                Sprite::from_image(shadow),
                Transform::from_translation(Vec3::new(
                    0.0,
                    -(FRAME_H as f32) / 2.0 + FEET_DROP_PX + 2.0,
                    -0.1,
                )),
            ));
        });
}

/// Reveal the window once the renderer has produced a few frames, so the
/// user never sees the pre-first-frame opaque flash (bevy's documented
/// pattern for transparent/undecorated windows).
fn reveal_window(mut window: Query<&mut Window, With<PrimaryWindow>>, frames: Res<FrameCount>) {
    if frames.0 == 3 {
        if let Ok(mut window) = window.single_mut() {
            window.visible = true;
        }
    }
}

fn rgba_to_bevy(img: RgbaImage) -> Image {
    Image::from_dynamic(
        image::DynamicImage::ImageRgba8(img),
        true,
        RenderAssetUsages::default(),
    )
}

/// Soft radial-gradient ellipse, native-pixel sized for a 192-wide frame.
fn shadow_image() -> RgbaImage {
    let (w, h) = (
        (FRAME_W as f32 * 0.55) as u32,
        ((FRAME_W as f32 * 0.55) * 0.28) as u32,
    );
    let mut img = RgbaImage::new(w.max(1), h.max(3));
    let (cx, cy) = (img.width() as f32 / 2.0, img.height() as f32 / 2.0);
    for y in 0..img.height() {
        for x in 0..img.width() {
            let dx = (x as f32 - cx) / cx;
            let dy = (y as f32 - cy) / cy;
            let d = (dx * dx + dy * dy).sqrt();
            // Opaque center fading out by 70% radius, matching the CSS
            // radial-gradient stop; 0.35 splits the themed 0.2/0.55 alphas.
            let alpha = ((1.0 - d / 0.7).clamp(0.0, 1.0) * 0.35 * 255.0) as u8;
            img.put_pixel(x, y, image::Rgba([0, 0, 0, alpha]));
        }
    }
    img
}
