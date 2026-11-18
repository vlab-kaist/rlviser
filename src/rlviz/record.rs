//! Video recording: while recording, the timeline advances by a fixed amount of game time per
//! rendered frame and every frame is captured (`Screenshot`) and piped to ffmpeg. The video is
//! therefore exact in game time however slowly the frames render.

use std::{
    collections::BTreeMap,
    io::Write,
    path::PathBuf,
    process::{Child, ChildStdin, Command, Stdio},
    thread::{self, JoinHandle},
};

use bevy::{
    prelude::*,
    render::{
        render_resource::TextureFormat,
        view::screenshot::{Screenshot, ScreenshotCaptured},
    },
};
use crossbeam_channel::Sender;

/// Recording options from the command line.
#[derive(Clone, Debug)]
pub struct RecordConfig {
    /// Start recording automatically to this file, then quit when done.
    pub path: Option<PathBuf>,
    pub fps: u32,
    /// Game-time speed of the video (2 = twice as fast as the game).
    pub speed: f32,
    /// Game seconds from the start of the replay.
    pub from: Option<f64>,
    pub to: Option<f64>,
}

impl Default for RecordConfig {
    fn default() -> Self {
        Self {
            path: None,
            fps: 60,
            speed: 1.,
            from: None,
            to: None,
        }
    }
}

/// An ongoing recording.
pub struct Session {
    pub path: PathBuf,
    pub fps: u32,
    pub speed: f32,
    /// Stop after the frame at this tick (or at the end of the timeline).
    pub end_tick: Option<u64>,
    /// Quit the app when finished (command line recording).
    pub exit_when_done: bool,
    pub frames: u64,
    tx: Option<Sender<(u64, Image)>>,
    writer: Option<JoinHandle<Result<(), String>>>,
}

impl Session {
    pub fn start(path: PathBuf, fps: u32, speed: f32, end_tick: Option<u64>, exit_when_done: bool) -> Self {
        let (tx, rx) = crossbeam_channel::unbounded::<(u64, Image)>();
        let out = path.clone();
        let writer = thread::spawn(move || {
            let mut encoder: Option<(Child, ChildStdin, UVec2)> = None;
            // Screenshots can arrive out of order; write them by index.
            let mut pending = BTreeMap::new();
            let mut next = 0;
            for (index, image) in rx {
                pending.insert(index, image);
                while let Some(image) = pending.remove(&next) {
                    next += 1;
                    let size = image.size();
                    if encoder.is_none() {
                        encoder = Some(spawn_ffmpeg(&out, fps, size, image.texture_descriptor.format)?);
                    }
                    let (_, stdin, enc_size) = encoder.as_mut().unwrap();
                    if *enc_size != size {
                        // The window was resized; ffmpeg can't change size mid-stream.
                        continue;
                    }
                    let Some(data) = &image.data else { continue };
                    stdin.write_all(data).map_err(|e| format!("ffmpeg: {e}"))?;
                }
            }
            if let Some((mut child, stdin, _)) = encoder {
                drop(stdin);
                let status = child.wait().map_err(|e| format!("ffmpeg: {e}"))?;
                if !status.success() {
                    return Err(format!("ffmpeg exited with {status}"));
                }
            }
            Ok(())
        });
        Self {
            path,
            fps,
            speed,
            end_tick,
            exit_when_done,
            frames: 0,
            tx: Some(tx),
            writer: Some(writer),
        }
    }

    /// Captures the frame being rendered now.
    pub fn capture(&mut self, commands: &mut Commands) {
        let Some(tx) = self.tx.clone() else { return };
        let index = self.frames;
        self.frames += 1;
        commands
            .spawn(Screenshot::primary_window())
            .observe(move |captured: On<ScreenshotCaptured>| {
                drop(tx.send((index, captured.image.clone())));
            });
    }

    /// Stops capturing. The writer finishes once the screenshots in flight have arrived (their
    /// observers hold the last senders); poll it with [`Session::poll`] without blocking the app.
    pub fn stop(&mut self) {
        drop(self.tx.take());
    }

    /// `Some` once the video file is complete (or failed).
    pub fn poll(&mut self) -> Option<Result<PathBuf, String>> {
        if !self.writer.as_ref().is_none_or(JoinHandle::is_finished) {
            return None;
        }
        Some(match self.writer.take().map(JoinHandle::join) {
            Some(Ok(Ok(()))) | None => Ok(self.path.clone()),
            Some(Ok(Err(e))) => Err(e),
            Some(Err(_)) => Err(String::from("video writer panicked")),
        })
    }
}

fn spawn_ffmpeg(path: &PathBuf, fps: u32, size: UVec2, format: TextureFormat) -> Result<(Child, ChildStdin, UVec2), String> {
    let pix_fmt = match format {
        TextureFormat::Bgra8Unorm | TextureFormat::Bgra8UnormSrgb => "bgra",
        TextureFormat::Rgba8Unorm | TextureFormat::Rgba8UnormSrgb => "rgba",
        other => return Err(format!("unsupported screenshot format {other:?}")),
    };
    let mut child = Command::new("ffmpeg")
        .args(["-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", pix_fmt, "-s"])
        .arg(format!("{}x{}", size.x, size.y))
        .args(["-r", &fps.to_string(), "-i", "-"])
        // yuv420p needs even dimensions
        .args(["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", "medium", "-crf", "18"])
        .args(["-pix_fmt", "yuv420p", "-movflags", "+faststart"])
        .arg(path)
        .stdin(Stdio::piped())
        .spawn()
        .map_err(|e| format!("can't start ffmpeg (is it installed?): {e}"))?;
    let stdin = child.stdin.take().unwrap();
    Ok((child, stdin, size))
}

/// A file name next to the replay (or in the working directory) for a recording started from the UI.
pub fn default_path(replay: Option<&PathBuf>) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs());
    let name = match replay.and_then(|p| p.file_stem()) {
        Some(stem) => format!("{}-{stamp}.mp4", stem.to_string_lossy()),
        None => format!("rlviz-{stamp}.mp4"),
    };
    replay
        .and_then(|p| p.parent())
        .map_or_else(|| PathBuf::from(&name), |dir| dir.join(&name))
}
