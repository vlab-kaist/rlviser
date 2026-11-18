//! rlviz replay/stream format, version 1 (see `docs/rlviz_format.md`).
//!
//! A stream is a sequence of MessagePack maps: one [`Header`] followed by any number of [`Frame`]s.
//! Files wrap the same stream in zstd. Unknown keys are ignored so producers can add fields
//! without bumping the version.

use serde::Deserialize;

pub const FORMAT_NAME: &str = "rlviz";
pub const FORMAT_VERSION: u32 = 1;

pub type V3 = [f32; 3];
pub type Rgba = [f32; 4];

#[derive(Deserialize, Clone, Debug)]
pub struct Header {
    pub format: String,
    pub version: u32,
    /// "soccar", "hoops", "heatseeker", "snowday", "dropshot" or "void"
    pub game_mode: String,
    #[serde(default = "default_tick_rate")]
    pub tick_rate: f32,
    #[serde(default)]
    pub pads: Vec<PadConfig>,
    #[serde(default)]
    pub cars: Vec<CarHeader>,
}

const fn default_tick_rate() -> f32 {
    120.
}

#[derive(Deserialize, Clone, Debug)]
pub struct PadConfig {
    pub pos: V3,
    pub big: bool,
}

#[derive(Deserialize, Clone, Debug)]
pub struct CarHeader {
    pub id: u64,
    pub team: u8,
    /// Missing: an Octane.
    #[serde(default)]
    pub config: Option<CarConfig>,
}

#[derive(Deserialize, Clone, Debug)]
pub struct CarConfig {
    pub hitbox_size: V3,
    pub hitbox_offset: V3,
    pub front_wheels: WheelPair,
    pub back_wheels: WheelPair,
    #[serde(default)]
    pub dodge_deadzone: f32,
}

#[derive(Deserialize, Clone, Debug)]
pub struct WheelPair {
    pub radius: f32,
    pub suspension_rest: f32,
    pub offset: V3,
}

#[derive(Deserialize, Clone, Debug)]
pub struct Frame {
    pub tick: u64,
    pub ball: Body,
    #[serde(default)]
    pub cars: Vec<Car>,
    /// Active flag per pad, in header order.
    #[serde(default)]
    pub pads: Vec<bool>,
    /// Debug draw groups. A group stays visible on later frames until a frame carries a group
    /// with the same name again (an empty `prims` list clears it).
    #[serde(default)]
    pub draw: Vec<DrawGroup>,
}

#[derive(Deserialize, Clone, Debug)]
pub struct Body {
    pub pos: V3,
    pub vel: V3,
    pub ang_vel: V3,
    /// Rotation matrix rows: forward, right, up.
    pub rot: [f32; 9],
}

#[derive(Deserialize, Clone, Debug)]
pub struct Car {
    pub id: u64,
    #[serde(flatten)]
    pub body: Body,
    #[serde(default)]
    pub boost: f32,
    #[serde(default)]
    pub on_ground: bool,
    #[serde(default)]
    pub wheels: [bool; 4],
    #[serde(default)]
    pub jumped: bool,
    #[serde(default)]
    pub double_jumped: bool,
    #[serde(default)]
    pub flipped: bool,
    #[serde(default)]
    pub demoed: bool,
    #[serde(default)]
    pub supersonic: bool,
    #[serde(default)]
    pub boosting: bool,
    /// throttle, steer, pitch, yaw, roll, jump, boost, handbrake
    #[serde(default)]
    pub controls: [f32; 8],
}

#[derive(Deserialize, Clone, Debug)]
pub struct DrawGroup {
    pub name: String,
    #[serde(default)]
    pub prims: Vec<Prim>,
}

/// World positions are in Rocket League units (z up). Colors are linear-ish sRGBA in 0..1.
#[derive(Deserialize, Clone, Debug)]
#[serde(tag = "t", rename_all = "lowercase")]
pub enum Prim {
    Line { a: V3, b: V3, color: Rgba },
    Polyline { pts: Vec<V3>, color: Rgba },
    Arrow { a: V3, b: V3, color: Rgba },
    /// `fill`: a solid (shaded) ball instead of a wireframe one.
    Sphere {
        c: V3,
        r: f32,
        color: Rgba,
        #[serde(default)]
        fill: bool,
    },
    /// A box of full extents `size` (along forward, right, up of `rot`), centred at `c`.
    /// `rot`: rotation matrix rows forward, right, up (as a body's `rot`); default axis-aligned.
    Box {
        c: V3,
        size: V3,
        #[serde(default)]
        rot: Option<[f32; 9]>,
        color: Rgba,
        #[serde(default)]
        fill: bool,
    },
    /// Shaded triangles: a surface, or the boundary of a volume. `tri` indexes `v`. `colors`
    /// (one per vertex) replaces `color`, for a value shown over a surface. `wire` also draws the
    /// edges.
    Mesh {
        v: Vec<V3>,
        tri: Vec<[u32; 3]>,
        color: Rgba,
        #[serde(default)]
        colors: Option<Vec<Rgba>>,
        #[serde(default)]
        wire: bool,
    },
    /// Label anchored at a world position.
    Text { pos: V3, text: String, color: Rgba },
    /// Label at a screen position, fractions of the window size from the top left.
    Text2d { pos: [f32; 2], text: String, color: Rgba },
    /// A primitive this viewer doesn't know (written for a newer one): skipped.
    #[serde(other)]
    Unknown,
}

impl Prim {
    /// Drawn as a mesh entity rather than with gizmos.
    pub const fn is_solid(&self) -> bool {
        matches!(self, Self::Sphere { fill: true, .. } | Self::Box { fill: true, .. } | Self::Mesh { .. })
    }
}
