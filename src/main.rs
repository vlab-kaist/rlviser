#![allow(
    clippy::too_many_arguments,
    clippy::needless_pass_by_value,
    clippy::module_name_repetitions,
    clippy::significant_drop_tightening,
    clippy::large_enum_variant
)]

mod assets;
mod camera;
mod flat;
mod mesh;
mod renderer;
mod rlviz;
mod settings;
mod spectator;
mod udp;

use std::{env, path::PathBuf};

use bevy::{
    image::{ImageAddressMode, ImageSamplerDescriptor},
    log::LogPlugin,
    prelude::*,
    window::PresentMode,
};
use settings::{cache_handler, gui};
use tracing::Level;

#[derive(Clone, Eq, PartialEq, Debug, Hash, Default, States)]
enum GameLoadState {
    #[default]
    Cache,
    Connect,
    FieldExtra,
    Despawn,
    Field,
    None,
}

#[derive(Resource)]
pub struct ServerPort {
    primary_port: u16,
    secondary_port: u16,
}

/// Splits off the rlviz options (see `docs/rlviz.md`); the remaining positional arguments are the
/// original UDP ports. Also returns the window size.
fn parse_args() -> (rlviz::RlvizConfig, Vec<String>, Option<(u32, u32)>) {
    fn value<T: std::str::FromStr>(flag: &str, arg: Option<String>) -> T {
        arg.and_then(|s| s.parse().ok())
            .unwrap_or_else(|| panic!("{flag} needs a valid value"))
    }

    let mut config = rlviz::RlvizConfig {
        replay: None,
        port: rlviz::DEFAULT_PORT,
        record: rlviz::record::RecordConfig::default(),
        camera: None,
        follow: None,
        follow_team: None,
        follow_car: None,
        looping: false,
    };
    let mut window = None;
    let mut positional = Vec::new();
    let mut args = env::args().skip(1);

    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--replay" => config.replay = args.next().map(PathBuf::from),
            "--loop" => config.looping = true,
            "--rlviz-port" => config.port = value(&arg, args.next()),
            "--record" => config.record.path = args.next().map(PathBuf::from),
            "--fps" => config.record.fps = value(&arg, args.next()),
            "--record-speed" => config.record.speed = value(&arg, args.next()),
            "--from" => config.record.from = Some(value(&arg, args.next())),
            "--to" => config.record.to = Some(value(&arg, args.next())),
            "--camera" => {
                // X,Y,Z:TX,TY,TZ (position : look-at point, game coordinates)
                let spec: String = value(&arg, args.next());
                let point = |s: &str| -> [f32; 3] {
                    let v: Vec<f32> = s.split(',').map(|x| x.trim().parse().expect("--camera X,Y,Z:TX,TY,TZ")).collect();
                    v.try_into().expect("--camera X,Y,Z:TX,TY,TZ")
                };
                let (pos, target) = spec.split_once(':').expect("--camera X,Y,Z:TX,TY,TZ");
                config.camera = Some((point(pos), point(target)));
            }
            "--follow" => {
                // X,Y,Z: camera offset from the (smoothed) ball, game coordinates
                let spec: String = value(&arg, args.next());
                let v: Vec<f32> = spec.split(',').map(|x| x.trim().parse().expect("--follow X,Y,Z")).collect();
                config.follow = Some(v.try_into().expect("--follow X,Y,Z"));
                // starts on the free camera like --camera
                config.camera.get_or_insert(([0., -3000., 1500.], [0., 0., 0.]));
            }
            "--follow-team" => config.follow_team = Some(value(&arg, args.next())),
            "--follow-car" => config.follow_car = Some(value(&arg, args.next())),
            "--window" => {
                let size: String = value(&arg, args.next());
                let (w, h) = size.split_once('x').expect("--window WIDTHxHEIGHT");
                window = Some((w.parse().expect("--window width"), h.parse().expect("--window height")));
            }
            _ if arg.parse::<u16>().is_err() && config.replay.is_none() => config.replay = Some(PathBuf::from(arg)),
            _ => positional.push(arg),
        }
    }

    (config, positional, window)
}

fn main() {
    let (rlviz_config, positional, window_size) = parse_args();
    let mut args = positional.into_iter();

    // read the first argument and treat it as the port to connect to (u16)
    let primary_port = args.next().and_then(|s| s.parse::<u16>().ok()).unwrap_or(34254);
    // read the second argument and treat it as the port to bind the UDP socket to (u16)
    let secondary_port = args.next().and_then(|s| s.parse::<u16>().ok()).unwrap_or(45243);

    #[cfg(debug_assertions)]
    assets::umodel::uncook().unwrap();

    App::new()
        .insert_resource(ServerPort {
            primary_port,
            secondary_port,
        })
        .insert_resource(rlviz_config)
        .add_plugins((
            DefaultPlugins
                .set(TaskPoolPlugin {
                    task_pool_options: TaskPoolOptions::with_num_threads(if cfg!(feature = "threaded") { 3 } else { 1 }),
                })
                .set(LogPlugin {
                    level: if cfg!(debug_assertions) { Level::INFO } else { Level::ERROR },
                    filter: if cfg!(debug_assertions) {
                        String::from("wgpu=error,naga=warn")
                    } else {
                        String::new()
                    },
                    ..Default::default()
                })
                .set(ImagePlugin {
                    default_sampler: ImageSamplerDescriptor {
                        address_mode_u: ImageAddressMode::Repeat,
                        address_mode_v: ImageAddressMode::Repeat,
                        address_mode_w: ImageAddressMode::Repeat,
                        ..default()
                    },
                })
                .set(WindowPlugin {
                    primary_window: Some(Window {
                        title: "RLViser".into(),
                        present_mode: PresentMode::AutoNoVsync,
                        resolution: window_size.map_or_else(default, |(w, h)| (w, h).into()),
                        ..default()
                    }),
                    ..default()
                }),
            cache_handler::CachePlugin,
            camera::CameraPlugin,
            gui::DebugOverlayPlugin,
            mesh::FieldLoaderPlugin,
            udp::RocketSimPlugin,
            assets::AssetsLoaderPlugin,
            rlviz::RlvizPlugin,
        ))
        .init_state::<GameLoadState>()
        .run();
}
