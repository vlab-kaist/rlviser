//! rlviz: replay files and live streams with a scrubbable timeline and debug draw groups.
//!
//! Frames come from [`source`] threads, are kept in a [`Timeline`], and the frame under the cursor
//! is fed to the stock rlviser pipeline as a `GameState` (through [`UdpInjector`]), so cars, ball,
//! pads and cameras behave exactly as with the UDP protocol. Debug primitives are drawn with gizmos
//! (3D) and egui (labels). See `docs/rlviz.md`.

mod convert;
pub mod format;
pub mod record;
mod solids;
mod source;

use std::{collections::BTreeMap, path::PathBuf};

use bevy::{prelude::*, window::PrimaryWindow};
use bevy_egui::{EguiContext, EguiPrimaryContextPass, PrimaryEguiContext, egui};
use crossbeam_channel::Receiver;

use crate::{
    camera::PrimaryCamera,
    settings::options::{MenuFocused, Options},
    udp::{ApplyUdpUpdates, ToBevyVec, UdpInjector, UdpUpdate},
};
use format::{DrawGroup, Frame, Header, Prim, Rgba};
use source::SourceMsg;

/// Command line options for rlviz.
#[derive(Resource, Clone)]
pub struct RlvizConfig {
    /// Replay file to open at start.
    pub replay: Option<PathBuf>,
    /// TCP port for live streams (127.0.0.1).
    pub port: u16,
    pub record: record::RecordConfig,
    /// `--loop`: play the replay over and over.
    pub looping: bool,
    /// Fixed camera (position, look-at point) in game coordinates, from `--camera`.
    pub camera: Option<([f32; 3], [f32; 3])>,
    /// `--follow`: free camera kept at this offset (game coordinates) from the smoothed ball.
    pub follow: Option<[f32; 3]>,
    /// `--follow-team`: also keep the car of this team nearest to the ball in view.
    pub follow_team: Option<u8>,
    /// `--follow-car`: follow this car instead of the ball, the offset turned so +x points from the car
    /// to the ball (x toward the ball, y left, z up).
    pub follow_car: Option<u64>,
}

pub const DEFAULT_PORT: u16 = 45300;

#[derive(Resource)]
struct SourceRx(Receiver<SourceMsg>);

const SPEEDS: [f32; 9] = [0.05, 0.1, 0.25, 0.5, 1., 2., 4., 8., 16.];

#[derive(Resource)]
pub struct Timeline {
    header: Option<Header>,
    label: String,
    live: bool,
    ended: bool,
    error: Option<String>,
    frames: Vec<Frame>,
    /// For each draw group name, the frame indices that carry it (ascending).
    group_frames: BTreeMap<String, Vec<usize>>,
    cursor: usize,
    playing: bool,
    speed: f32,
    /// Simulated seconds played since the cursor frame.
    clock: f64,
    /// While live, keep the cursor on the newest frame.
    follow: bool,
    /// Frame last sent to the viewer.
    shown: Option<usize>,
    /// Start again from the first frame after the end (replays, not live streams).
    looping: bool,
    /// Bumped whenever a new source replaces the frames (frame indices start over).
    generation: u64,
}

impl Default for Timeline {
    fn default() -> Self {
        Self {
            header: None,
            label: String::new(),
            live: false,
            ended: false,
            error: None,
            frames: Vec::new(),
            group_frames: BTreeMap::new(),
            cursor: 0,
            playing: true,
            speed: 1.,
            clock: 0.,
            follow: false,
            shown: None,
            looping: false,
            generation: 0,
        }
    }
}

impl Timeline {
    fn tick_rate(&self) -> f64 {
        f64::from(self.header.as_ref().map_or(120., |h| h.tick_rate))
    }

    fn seek(&mut self, index: usize) {
        if self.frames.is_empty() {
            return;
        }
        self.cursor = index.min(self.frames.len() - 1);
        self.clock = 0.;
        self.follow = self.live && !self.ended && self.cursor + 1 == self.frames.len() && self.playing;
    }

    /// Moves by `seconds` of game time (negative goes back).
    fn seek_time(&mut self, seconds: f64) {
        if self.frames.is_empty() {
            return;
        }
        let target = self.frames[self.cursor].tick as f64 + seconds * self.tick_rate();
        let index = self.frames.partition_point(|f| (f.tick as f64) <= target).saturating_sub(1);
        self.seek(index);
    }

    fn step(&mut self, frames: isize) {
        self.playing = false;
        self.seek(self.cursor.saturating_add_signed(frames));
    }

    fn toggle_play(&mut self) {
        self.playing = !self.playing;
        if self.playing && !self.live && self.cursor + 1 >= self.frames.len() {
            self.seek(0);
        }
        self.clock = 0.;
    }

    /// The draw groups in effect at the cursor: for each name, the latest frame at or before it.
    fn active_groups(&self) -> impl Iterator<Item = &DrawGroup> {
        self.active_groups_at().map(|(_, group)| group)
    }

    /// Like [`Timeline::active_groups`], with the index of the frame each group comes from.
    fn active_groups_at(&self) -> impl Iterator<Item = (usize, &DrawGroup)> {
        self.group_frames.iter().filter_map(|(name, indices)| {
            let pos = indices.partition_point(|&i| i <= self.cursor);
            let index = *indices.get(pos.checked_sub(1)?)?;
            Some((index, self.frames[index].draw.iter().find(|g| &g.name == name)?))
        })
    }
}

/// Video recording state.
#[derive(Resource, Default)]
struct Recording {
    session: Option<record::Session>,
    /// Sessions that stopped capturing and wait for ffmpeg to finish.
    finishing: Vec<record::Session>,
    /// Frames rendered since the first state was shown (command line recording waits for assets).
    warmup: u32,
    cli_started: bool,
    /// The menu's open state before recording hid it.
    menu_was_open: Option<bool>,
    /// The last frame is captured: stop in the next frame.
    stop_next: bool,
    status: Option<String>,
}

impl Recording {
    fn active(&self) -> bool {
        self.session.is_some()
    }
}

/// Which draw groups are shown, by name. New groups start visible.
#[derive(Resource, Default)]
struct LayerToggles(BTreeMap<String, bool>);

impl LayerToggles {
    fn shown(&self, name: &str) -> bool {
        self.0.get(name).copied().unwrap_or(true)
    }
}

/// `--camera`: switch to the free camera once, placed and aimed as given. It stays free (and can be
/// moved) afterwards; the camera keys switch away from it as usual.
fn place_camera(
    config: Res<RlvizConfig>,
    mut options: ResMut<Options>,
    mut cameras: Query<&mut Transform, With<PrimaryCamera>>,
    mut done: Local<bool>,
) {
    let Some((pos, target)) = config.camera else { return };
    if *done {
        return;
    }
    let Ok(mut transform) = cameras.single_mut() else { return };
    *transform = Transform::from_translation(pos.to_bevy()).looking_at(target.to_bevy(), Vec3::Y);
    options.camera_state = PrimaryCamera::Spectator;
    *done = true;
}

/// Seconds of ball positions (each side of the cursor) averaged into the `--follow` focus.
const FOLLOW_WINDOW: f64 = 0.75;
/// A ball jump larger than this between frames is a cut (next play), which the average stops at.
const FOLLOW_CUT: f32 = 600.;
/// `--follow-team`: ball-to-car distance that fits at the plain `--follow` offset; farther apart, the
/// offset is scaled up by distance / this.
const FOLLOW_FIT: f32 = 1500.;

/// `--follow`: while the free camera is active, keep it at a fixed offset from the ball's position
/// averaged over the frames around the cursor (a pure function of the cursor, so scrubbing and
/// recordings are reproducible), clamped inside the arena so walls don't hide the play.
/// With `--follow-team`, the focus is the midpoint of the ball and that team's car nearest to it
/// (cars parked below the floor are skipped), and the offset grows with their distance so both fit.
/// With `--follow-car`, the focus is that car and the offset turns with the car-to-ball direction, so
/// e.g. `0,-900,250` watches the car from its side as it drives at the ball.
fn follow_camera(
    config: Res<RlvizConfig>,
    timeline: Res<Timeline>,
    options: Res<Options>,
    mut cameras: Query<&mut Transform, With<PrimaryCamera>>,
) {
    let Some(offset) = config.follow else { return };
    if options.camera_state != PrimaryCamera::Spectator || timeline.frames.is_empty() {
        return;
    }
    let Ok(mut transform) = cameras.single_mut() else { return };
    let frames = &timeline.frames;
    let team_ids: Vec<u64> = match (config.follow_team, &timeline.header) {
        (Some(team), Some(header)) => header.cars.iter().filter(|c| c.team == team).map(|c| c.id).collect(),
        _ => Vec::new(),
    };
    // (focus, ball-to-car distance) of one frame
    let car_pos = |i: usize, id: u64| frames[i].cars.iter().find(|c| c.id == id).map(|c| Vec3::from_array(c.body.pos));
    let point = |i: usize| -> (Vec3, f32) {
        let ball = Vec3::from_array(frames[i].ball.pos);
        if let Some(car) = config.follow_car.and_then(|id| car_pos(i, id)) {
            return (car, 0.);
        }
        let car = frames[i]
            .cars
            .iter()
            .filter(|c| team_ids.contains(&c.id) && !c.demoed && c.body.pos[2] > -500.)
            .map(|c| Vec3::from_array(c.body.pos))
            .min_by(|a, b| a.distance(ball).total_cmp(&b.distance(ball)));
        car.map_or((ball, 0.), |car| ((ball + car) / 2., ball.distance(car)))
    };
    let ball = |i: usize| Vec3::from_array(frames[i].ball.pos);
    // car-to-ball direction on the floor, summed over the window (--follow-car)
    let heading = |i: usize| config.follow_car.and_then(|id| car_pos(i, id)).map_or(Vec3::ZERO, |car| (ball(i) - car).with_z(0.).normalize_or_zero());
    let same_play = |a: usize, b: usize| ball(a).distance(ball(b)) < FOLLOW_CUT && point(a).0.distance(point(b).0) < FOLLOW_CUT;
    let at = timeline.cursor.min(frames.len() - 1);
    let span = (FOLLOW_WINDOW * timeline.tick_rate()) as u64;
    let tick = frames[at].tick;
    let (mut sum, mut spread) = point(at);
    let mut dir = heading(at);
    let mut n = 1.;
    let mut i = at;
    while i > 0 && frames[i - 1].tick + span >= tick && frames[i - 1].tick <= frames[i].tick && same_play(i - 1, i) {
        i -= 1;
        let (p, d) = point(i);
        dir += heading(i);
        sum += p;
        spread += d;
        n += 1.;
    }
    let mut i = at;
    while i + 1 < frames.len() && frames[i + 1].tick <= tick + span && frames[i + 1].tick >= frames[i].tick && same_play(i + 1, i) {
        i += 1;
        let (p, d) = point(i);
        dir += heading(i);
        sum += p;
        spread += d;
        n += 1.;
    }
    let focus = sum / n;
    let scale = (spread / n / FOLLOW_FIT).max(1.);
    let mut offset = Vec3::from_array(offset);
    if config.follow_car.is_some() {
        let x = dir.normalize_or(Vec3::Y);
        let y = Vec3::new(-x.y, x.x, 0.);
        offset = x * offset.x + y * offset.y + Vec3::Z * offset.z;
    }
    let eye = (focus + offset * scale).clamp(Vec3::new(-3900., -4900., 150.), Vec3::new(3900., 4900., 1900.));
    *transform = Transform::from_translation(eye.to_array().to_bevy()).looking_at(focus.to_array().to_bevy(), Vec3::Y);
}

fn start_sources(config: Res<RlvizConfig>, mut timeline: ResMut<Timeline>, mut commands: Commands) {
    timeline.looping = config.looping;
    let (tx, rx) = crossbeam_channel::unbounded();
    if let Some(path) = &config.replay {
        source::spawn_file_reader(path.clone(), tx.clone());
    }
    source::spawn_listener(config.port, tx);
    commands.insert_resource(SourceRx(rx));
}

fn ingest(rx: Res<SourceRx>, mut timeline: ResMut<Timeline>, mut toggles: ResMut<LayerToggles>) {
    for msg in rx.0.try_iter() {
        match msg {
            SourceMsg::Start { header, label, live } => {
                *timeline = Timeline {
                    header: Some(header),
                    label,
                    live,
                    follow: live,
                    speed: timeline.speed,
                    looping: timeline.looping,
                    generation: timeline.generation + 1,
                    ..Default::default()
                };
            }
            SourceMsg::Frame(frame) => {
                let index = timeline.frames.len();
                for group in &frame.draw {
                    toggles.0.entry(group.name.clone()).or_insert(true);
                    timeline.group_frames.entry(group.name.clone()).or_default().push(index);
                }
                timeline.frames.push(frame);
                if timeline.follow {
                    timeline.cursor = index;
                }
            }
            SourceMsg::End => {
                timeline.ended = true;
                timeline.follow = false;
            }
            SourceMsg::Error(e) => {
                error!("{e}");
                timeline.error = Some(e);
            }
        }
    }
}

/// Seconds the last frame stays on screen before a loop starts over.
const LOOP_PAUSE: f64 = 1.0;

fn advance(time: Res<Time>, recording: Res<Recording>, mut timeline: ResMut<Timeline>) {
    if !timeline.playing || timeline.follow || timeline.frames.is_empty() {
        return;
    }

    let tick_rate = timeline.tick_rate();
    // While recording, each rendered frame is one video frame of game time.
    timeline.clock += match &recording.session {
        Some(session) => f64::from(session.speed) / f64::from(session.fps),
        None => time.delta_secs_f64() * f64::from(timeline.speed),
    };
    let target = timeline.frames[timeline.cursor].tick as f64 + timeline.clock * tick_rate;

    // A recording with an end never moves past it, whatever order this runs in relative to the
    // capture (the frame after the end can be a different run, or one that clears the drawings).
    let end = recording.session.as_ref().and_then(|s| s.end_tick).unwrap_or(u64::MAX);
    let mut cursor = timeline.cursor;
    while cursor + 1 < timeline.frames.len() && timeline.frames[cursor + 1].tick as f64 <= target && timeline.frames[cursor + 1].tick <= end {
        cursor += 1;
    }
    if cursor != timeline.cursor {
        timeline.clock = (target - timeline.frames[cursor].tick as f64) / tick_rate;
        timeline.cursor = cursor;
    }

    if timeline.cursor + 1 == timeline.frames.len() {
        if timeline.live && !timeline.ended {
            timeline.follow = true;
        } else if timeline.looping && !recording.active() {
            // hold the last frame for a moment, then start over (once the whole file is read)
            if timeline.ended && timeline.clock >= LOOP_PAUSE {
                timeline.seek(0);
            }
        } else {
            timeline.playing = false;
        }
    }
}

/// Sends the cursor frame to the viewer. Normal playback lets the viewer interpolate between
/// frames; jumps, a paused timeline and recording show the frame exactly (`Snap`).
fn show_frame(injector: Option<Res<UdpInjector>>, recording: Res<Recording>, mut timeline: ResMut<Timeline>) {
    let Some(injector) = injector else { return };
    let Some(header) = &timeline.header else { return };
    if timeline.frames.is_empty() || timeline.shown == Some(timeline.cursor) {
        return;
    }

    let state = convert::to_game_state(header, &timeline.frames[timeline.cursor]);
    let contiguous = timeline.shown.is_some_and(|s| s + 1 == timeline.cursor);
    let smooth = contiguous && (timeline.playing || timeline.follow) && !recording.active();
    drop(injector.send(if smooth { UdpUpdate::State(state) } else { UdpUpdate::Snap(state) }));
    timeline.shown = Some(timeline.cursor);
}

fn start_recording(
    recording: &mut Recording,
    timeline: &mut Timeline,
    menu: &mut MenuFocused,
    path: PathBuf,
    config: &record::RecordConfig,
    end_tick: Option<u64>,
    exit_when_done: bool,
) {
    info!("recording to {}", path.display());
    recording.status = Some(format!("recording to {}", path.display()));
    recording.menu_was_open = Some(menu.0);
    menu.0 = false;
    timeline.playing = true;
    timeline.clock = 0.;
    recording.session = Some(record::Session::start(path, config.fps, config.speed, end_tick, exit_when_done));
}

fn stop_recording(recording: &mut Recording, menu: &mut MenuFocused) {
    if let Some(mut session) = recording.session.take() {
        session.stop();
        recording.finishing.push(session);
    }
    if let Some(open) = recording.menu_was_open.take() {
        menu.0 = open;
    }
}

/// Starts the command line recording, captures frames, stops at the end and reaps finished files.
fn drive_recording(
    mut commands: Commands,
    config: Res<RlvizConfig>,
    mut recording: ResMut<Recording>,
    mut timeline: ResMut<Timeline>,
    mut menu: ResMut<MenuFocused>,
    mut exit: MessageWriter<AppExit>,
) {
    // Command line recording: wait until the replay is shown and cars/meshes had time to load.
    if let Some(path) = &config.record.path
        && !recording.cli_started
        && timeline.shown.is_some()
    {
        recording.warmup += 1;
        if recording.warmup >= 90 && (timeline.ended || !timeline.live) {
            recording.cli_started = true;
            let first = timeline.frames[0].tick;
            let tick_rate = timeline.tick_rate();
            let at = |seconds: f64| first + (seconds * tick_rate).round() as u64;
            if let Some(from) = config.record.from {
                let index = timeline.frames.partition_point(|f| f.tick < at(from));
                timeline.seek(index);
            } else {
                timeline.seek(0);
            }
            let end_tick = config.record.to.map(at);
            start_recording(&mut recording, &mut timeline, &mut menu, path.clone(), &config.record, end_tick, true);
            // Show the start frame before the first capture.
            return;
        }
    }

    if recording.stop_next {
        // The last frame was captured in the previous frame; stopping in the same frame would
        // show the UI again in that capture.
        recording.stop_next = false;
        stop_recording(&mut recording, &mut menu);
        timeline.playing = false;
    } else if let Some(session) = &mut recording.session {
        session.capture(&mut commands);
        let tick = timeline.frames.get(timeline.cursor).map_or(0, |f| f.tick);
        let at_end = timeline.cursor + 1 >= timeline.frames.len() && !(timeline.live && !timeline.ended);
        if session.end_tick.is_some_and(|end| tick >= end) || at_end || !timeline.playing && !timeline.follow {
            recording.stop_next = true;
        }
    }

    let mut exit_now = false;
    let mut status = None;
    recording.finishing.retain_mut(|session| match session.poll() {
        None => true,
        Some(result) => {
            let msg = match result {
                Ok(path) => format!("saved {} ({} frames)", path.display(), session.frames),
                Err(e) => format!("recording failed: {e}"),
            };
            println!("{msg}");
            status = Some(msg);
            exit_now |= session.exit_when_done;
            false
        }
    });
    if status.is_some() {
        recording.status = status;
    }
    if exit_now {
        exit.write(AppExit::Success);
    }
}

fn color(c: Rgba) -> Color {
    Color::srgba(c[0], c[1], c[2], c[3])
}

fn draw_gizmos(timeline: Res<Timeline>, toggles: Res<LayerToggles>, mut gizmos: Gizmos) {
    for group in timeline.active_groups().filter(|g| toggles.shown(&g.name)) {
        for prim in &group.prims {
            match prim {
                Prim::Line { a, b, color: c } => gizmos.line(a.to_bevy(), b.to_bevy(), color(*c)),
                Prim::Polyline { pts, color: c } => {
                    gizmos.linestrip(pts.iter().map(|p| p.to_bevy()), color(*c));
                }
                Prim::Arrow { a, b, color: c } => {
                    let (a, b) = (a.to_bevy(), b.to_bevy());
                    let tip = (a.distance(b) * 0.25).clamp(5., 40.);
                    gizmos.arrow(a, b, color(*c)).with_tip_length(tip);
                }
                Prim::Sphere { c, r, color: col, fill: false } => {
                    gizmos.sphere(Isometry3d::from_translation(c.to_bevy()), *r, color(*col));
                }
                Prim::Box { c, size, rot, color: col, fill: false } => {
                    let (rotation, size) = solids::box_frame(*size, *rot);
                    gizmos.cube(Transform::from_translation(c.to_bevy()).with_rotation(rotation).with_scale(size), color(*col));
                }
                Prim::Mesh { v, tri, color: col, wire: true, .. } => {
                    for t in tri {
                        let [a, b, c] = t.map(|i| v.get(i as usize).map(|p| p.to_bevy()));
                        if let (Some(a), Some(b), Some(c)) = (a, b, c) {
                            gizmos.linestrip([a, b, c, a], color([0.1, 0.1, 0.1, col[3].max(0.6)]));
                        }
                    }
                }
                Prim::Sphere { .. } | Prim::Box { .. } | Prim::Mesh { .. } => {} // solids.rs
                Prim::Text { .. } | Prim::Text2d { .. } | Prim::Unknown => {}
            }
        }
    }
}

fn egui_color(c: Rgba) -> egui::Color32 {
    let u = |v: f32| (v.clamp(0., 1.) * 255.).round() as u8;
    egui::Color32::from_rgba_unmultiplied(u(c[0]), u(c[1]), u(c[2]), u(c[3]))
}

fn draw_labels(
    mut contexts: Single<&mut EguiContext, With<PrimaryEguiContext>>,
    timeline: Res<Timeline>,
    toggles: Res<LayerToggles>,
    camera: Query<(&Camera, &GlobalTransform), With<PrimaryCamera>>,
    window: Single<&Window, With<PrimaryWindow>>,
) {
    let ctx = contexts.get_mut();
    let Ok((camera, camera_transform)) = camera.single() else { return };
    // world_to_viewport gives logical pixels; egui works in points.
    let to_points = window.scale_factor() / ctx.pixels_per_point();
    let screen = ctx.content_rect();
    let painter = ctx.layer_painter(egui::LayerId::new(egui::Order::Background, egui::Id::new("rlviz_labels")));
    let font = egui::FontId::monospace(13.);

    for group in timeline.active_groups().filter(|g| toggles.shown(&g.name)) {
        for prim in &group.prims {
            match prim {
                Prim::Text { pos, text, color } => {
                    let Ok(p) = camera.world_to_viewport(camera_transform, pos.to_bevy()) else { continue };
                    let p = egui::pos2(p.x * to_points, p.y * to_points);
                    let galley = painter.layout_no_wrap(text.clone(), font.clone(), egui_color(*color));
                    let rect = egui::Align2::CENTER_BOTTOM.anchor_size(p, galley.size());
                    painter.rect_filled(rect.expand(2.), 3., egui::Color32::from_black_alpha(110));
                    painter.galley(rect.min, galley, egui_color(*color));
                }
                Prim::Text2d { pos, text, color } => {
                    let p = screen.min + egui::vec2(pos[0] * screen.width(), pos[1] * screen.height());
                    painter.text(p, egui::Align2::LEFT_TOP, text, font.clone(), egui_color(*color));
                }
                _ => {}
            }
        }
    }
}

fn toggle_recording(
    config: &RlvizConfig,
    recording: &mut Recording,
    timeline: &mut Timeline,
    menu: &mut MenuFocused,
) {
    if recording.active() {
        // this frame is already being captured; stop with the next one (see drive_recording)
        recording.stop_next = true;
    } else {
        let path = record::default_path(config.replay.as_ref());
        start_recording(recording, timeline, menu, path, &config.record, None, false);
    }
}

fn timeline_keys(
    mut contexts: Single<&mut EguiContext, With<PrimaryEguiContext>>,
    keys: Res<ButtonInput<KeyCode>>,
    config: Res<RlvizConfig>,
    mut timeline: ResMut<Timeline>,
    mut recording: ResMut<Recording>,
    mut menu: ResMut<MenuFocused>,
) {
    if contexts.get_mut().wants_keyboard_input() || timeline.frames.is_empty() {
        return;
    }
    if keys.just_pressed(KeyCode::F9) {
        toggle_recording(&config, &mut recording, &mut timeline, &mut menu);
    }
    if recording.active() {
        return;
    }
    if keys.just_pressed(KeyCode::KeyK) {
        timeline.toggle_play();
    }
    if keys.just_pressed(KeyCode::KeyJ) {
        timeline.seek_time(-1.);
    }
    if keys.just_pressed(KeyCode::KeyL) {
        timeline.seek_time(1.);
    }
    if keys.just_pressed(KeyCode::Comma) {
        timeline.step(-1);
    }
    if keys.just_pressed(KeyCode::Period) {
        timeline.step(1);
    }
    if keys.just_pressed(KeyCode::Home) {
        timeline.seek(0);
    }
    if keys.just_pressed(KeyCode::End) {
        let last = timeline.frames.len() - 1;
        timeline.seek(last);
    }
}

fn timeline_ui(
    mut contexts: Single<&mut EguiContext, With<PrimaryEguiContext>>,
    config: Res<RlvizConfig>,
    mut timeline: ResMut<Timeline>,
    mut toggles: ResMut<LayerToggles>,
    mut recording: ResMut<Recording>,
    mut menu: ResMut<MenuFocused>,
) {
    let ctx = contexts.get_mut();
    // Nothing of ours in the video.
    if recording.active() {
        return;
    }

    egui::TopBottomPanel::bottom("rlviz_timeline").show(ctx, |ui| {
        if let Some(e) = &timeline.error {
            ui.colored_label(egui::Color32::LIGHT_RED, e);
        }
        if timeline.frames.is_empty() {
            ui.label(match &timeline.header {
                Some(_) => format!("{}: waiting for frames", timeline.label),
                None => String::from("rlviz: no replay loaded, waiting for a live stream"),
            });
            return;
        }

        let tick_rate = timeline.tick_rate();
        let first_tick = timeline.frames[0].tick;
        let last = timeline.frames.len() - 1;

        ui.horizontal(|ui| {
            if ui.button("⏮").on_hover_text("Start (Home)").clicked() {
                timeline.seek(0);
            }
            if ui.button("◀").on_hover_text("Previous frame (,)").clicked() {
                timeline.step(-1);
            }
            let play = if timeline.playing { "⏸" } else { "▶" };
            if ui.button(play).on_hover_text("Play / pause (K)").clicked() {
                timeline.toggle_play();
            }
            if ui.button("▶|").on_hover_text("Next frame (.)").clicked() {
                timeline.step(1);
            }
            if ui.button("⏭").on_hover_text("End (End)").clicked() {
                timeline.seek(last);
            }

            let mut speed = timeline.speed;
            egui::ComboBox::from_id_salt("rlviz_speed")
                .width(60.)
                .selected_text(format!("{speed}x"))
                .show_ui(ui, |ui| {
                    for s in SPEEDS {
                        ui.selectable_value(&mut speed, s, format!("{s}x"));
                    }
                });
            timeline.speed = speed;
            ui.checkbox(&mut timeline.looping, "Loop").on_hover_text("Start over after the end");

            let tick = timeline.frames[timeline.cursor].tick;
            ui.monospace(format!(
                "tick {tick}  t={:.2}s  frame {}/{}",
                (tick - first_tick) as f64 / tick_rate,
                timeline.cursor,
                last
            ));
            if timeline.live && !timeline.ended {
                let text = if timeline.follow { "LIVE" } else { "live (behind)" };
                ui.colored_label(egui::Color32::LIGHT_RED, text);
            }
            if ui.button("Rec").on_hover_text("Record a video from here (F9 stops)").clicked() {
                toggle_recording(&config, &mut recording, &mut timeline, &mut menu);
            }
            ui.label(&timeline.label);
        });
        if let Some(status) = &recording.status {
            ui.label(status);
        }

        let mut cursor = timeline.cursor;
        ui.spacing_mut().slider_width = ui.available_width();
        if ui.add(egui::Slider::new(&mut cursor, 0..=last).show_value(false)).changed() {
            timeline.playing = false;
            timeline.seek(cursor);
        }
    });

    if !toggles.0.is_empty() {
        egui::Window::new("Layers").default_open(true).show(ctx, |ui| {
            for (name, shown) in &mut toggles.0 {
                ui.checkbox(shown, name);
            }
        });
    }
}

pub struct RlvizPlugin;

impl Plugin for RlvizPlugin {
    fn build(&self, app: &mut App) {
        app.insert_resource(Timeline::default())
            .insert_resource(LayerToggles::default())
            .insert_resource(Recording::default())
            .add_systems(Startup, start_sources)
            .add_systems(Update, (place_camera, follow_camera.after(show_frame)))
            .add_systems(Update, (ingest, advance, show_frame, drive_recording).chain().before(ApplyUdpUpdates))
            .add_systems(Update, draw_gizmos.after(show_frame))
            .add_systems(Update, solids::sync_solids.after(show_frame))
            .init_resource::<solids::Solids>()
            .add_systems(EguiPrimaryContextPass, (timeline_keys, timeline_ui, draw_labels).chain());
    }
}
