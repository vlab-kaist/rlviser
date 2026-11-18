//! rlviz frames -> the viewer's own `GameState`, so the existing car/ball/pad systems draw them.

use crate::flat::rocketsim::{
    BallState, BoostPadConfig, BoostPadInfo, BoostPadState, CarConfig, CarControls, CarInfo, CarState, GameMode, GameState,
    Mat3, PhysState, Team, Vec3, WheelPairConfig, WheelsWithContact,
};

use super::format::{self, Body, Frame, Header};

const fn v3(v: format::V3) -> Vec3 {
    Vec3 { x: v[0], y: v[1], z: v[2] }
}

fn phys(b: &Body) -> PhysState {
    let r = b.rot;
    PhysState {
        pos: v3(b.pos),
        rot_mat: Mat3 {
            forward: Vec3 { x: r[0], y: r[1], z: r[2] },
            right: Vec3 { x: r[3], y: r[4], z: r[5] },
            up: Vec3 { x: r[6], y: r[7], z: r[8] },
        },
        vel: v3(b.vel),
        ang_vel: v3(b.ang_vel),
    }
}

pub fn game_mode(name: &str) -> GameMode {
    match name {
        "soccar" => GameMode::Soccar,
        "hoops" => GameMode::Hoops,
        "heatseeker" => GameMode::Heatseeker,
        "snowday" => GameMode::Snowday,
        "dropshot" => GameMode::Dropshot,
        _ => GameMode::TheVoid,
    }
}

fn wheels(w: &format::WheelPair) -> WheelPairConfig {
    WheelPairConfig {
        wheel_radius: w.radius,
        suspension_rest_length: w.suspension_rest,
        connection_point_offset: v3(w.offset),
    }
}

fn car_config(c: &format::CarConfig) -> CarConfig {
    CarConfig {
        hitbox_size: v3(c.hitbox_size),
        hitbox_pos_offset: v3(c.hitbox_offset),
        front_wheels: wheels(&c.front_wheels),
        back_wheels: wheels(&c.back_wheels),
        three_wheels: false,
        dodge_deadzone: c.dodge_deadzone,
    }
}

/// Octane, used when the header does not describe a car.
fn default_car_config() -> CarConfig {
    car_config(&format::CarConfig {
        hitbox_size: [120.507, 86.6994, 38.6591],
        hitbox_offset: [13.8757, 0., 20.755],
        front_wheels: format::WheelPair {
            radius: 12.5,
            suspension_rest: 38.755,
            offset: [51.25, 25.9, 20.755],
        },
        back_wheels: format::WheelPair {
            radius: 15.,
            suspension_rest: 37.055,
            offset: [-33.75, 29.5, 20.755],
        },
        dodge_deadzone: 0.5,
    })
}

pub fn to_game_state(header: &Header, frame: &Frame) -> GameState {
    let cars = frame
        .cars
        .iter()
        .map(|car| {
            let info = header.cars.iter().find(|c| c.id == car.id);
            let c = car.controls;
            let state = CarState {
                physics: phys(&car.body),
                is_on_ground: car.on_ground,
                wheels_with_contact: WheelsWithContact {
                    front_left: car.wheels[0],
                    front_right: car.wheels[1],
                    rear_left: car.wheels[2],
                    rear_right: car.wheels[3],
                },
                has_jumped: car.jumped,
                has_double_jumped: car.double_jumped,
                has_flipped: car.flipped,
                boost: car.boost,
                is_boosting: car.boosting,
                is_supersonic: car.supersonic,
                is_demoed: car.demoed,
                last_controls: CarControls {
                    throttle: c[0],
                    steer: c[1],
                    pitch: c[2],
                    yaw: c[3],
                    roll: c[4],
                    jump: c[5] > 0.5,
                    boost: c[6] > 0.5,
                    handbrake: c[7] > 0.5,
                },
                ..Default::default()
            };
            CarInfo {
                id: car.id,
                team: if info.is_some_and(|i| i.team == 1) { Team::Orange } else { Team::Blue },
                state: Box::new(state),
                config: info.map_or_else(default_car_config, |i| car_config(&i.config)),
            }
        })
        .collect();

    let pads = header
        .pads
        .iter()
        .enumerate()
        .map(|(i, pad)| BoostPadInfo {
            config: BoostPadConfig {
                pos: v3(pad.pos),
                is_big: pad.big,
            },
            state: BoostPadState {
                is_active: frame.pads.get(i).copied().unwrap_or(true),
                ..Default::default()
            },
        })
        .collect();

    GameState {
        tick_rate: header.tick_rate,
        tick_count: frame.tick,
        game_mode: game_mode(&header.game_mode),
        cars: Some(cars),
        ball: BallState {
            physics: phys(&frame.ball),
            ..Default::default()
        },
        pads: Some(pads),
        tiles: None,
    }
}
