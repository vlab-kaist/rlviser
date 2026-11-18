//! Reader threads: a replay file (zstd) or live TCP connections. Both decode the same stream
//! (header, then frames) and hand the result to the timeline through a channel.

use std::{
    fs::File,
    io::{BufReader, ErrorKind, Read},
    net::TcpListener,
    path::PathBuf,
    thread,
};

use crossbeam_channel::Sender;
use serde::Deserialize;

use super::format::{FORMAT_NAME, FORMAT_VERSION, Frame, Header};

pub enum SourceMsg {
    /// A new stream started: drop the current timeline.
    Start { header: Header, label: String, live: bool },
    Frame(Frame),
    /// The stream ended normally.
    End,
    Error(String),
}

fn is_eof(err: &rmp_serde::decode::Error) -> bool {
    match err {
        rmp_serde::decode::Error::InvalidMarkerRead(e) | rmp_serde::decode::Error::InvalidDataRead(e) => {
            e.kind() == ErrorKind::UnexpectedEof
        }
        _ => false,
    }
}

/// Decodes one stream until it ends. Returns false when the receiver is gone.
fn pump<R: Read>(reader: R, label: String, live: bool, tx: &Sender<SourceMsg>) -> bool {
    let mut de = rmp_serde::Deserializer::new(reader);

    let header = match Header::deserialize(&mut de) {
        Ok(h) => h,
        Err(e) => return tx.send(SourceMsg::Error(format!("{label}: bad header: {e}"))).is_ok(),
    };
    if header.format != FORMAT_NAME || header.version > FORMAT_VERSION {
        let msg = format!(
            "{label}: unsupported stream {} v{} (this viewer reads {FORMAT_NAME} v{FORMAT_VERSION})",
            header.format, header.version
        );
        return tx.send(SourceMsg::Error(msg)).is_ok();
    }
    if tx.send(SourceMsg::Start { header, label: label.clone(), live }).is_err() {
        return false;
    }

    loop {
        match Frame::deserialize(&mut de) {
            Ok(frame) => {
                if tx.send(SourceMsg::Frame(frame)).is_err() {
                    return false;
                }
            }
            Err(e) if is_eof(&e) => return tx.send(SourceMsg::End).is_ok(),
            Err(e) => return tx.send(SourceMsg::Error(format!("{label}: bad frame: {e}"))).is_ok(),
        }
    }
}

pub fn spawn_file_reader(path: PathBuf, tx: Sender<SourceMsg>) {
    thread::spawn(move || {
        let label = path.display().to_string();
        let file = match File::open(&path) {
            Ok(f) => f,
            Err(e) => {
                drop(tx.send(SourceMsg::Error(format!("{label}: {e}"))));
                return;
            }
        };
        match zstd::Decoder::new(file) {
            Ok(dec) => {
                pump(BufReader::new(dec), label, false, &tx);
            }
            Err(e) => drop(tx.send(SourceMsg::Error(format!("{label}: {e}")))),
        }
    });
}

/// Accepts one live connection at a time; each new connection replaces the timeline.
pub fn spawn_listener(port: u16, tx: Sender<SourceMsg>) {
    thread::spawn(move || {
        let listener = match TcpListener::bind(("127.0.0.1", port)) {
            Ok(l) => l,
            Err(e) => {
                drop(tx.send(SourceMsg::Error(format!("rlviz listener on port {port}: {e}"))));
                return;
            }
        };
        for stream in listener.incoming() {
            let Ok(stream) = stream else { continue };
            let label = stream
                .peer_addr()
                .map_or_else(|_| String::from("live"), |a| format!("live {a}"));
            if !pump(BufReader::new(stream), label, true, &tx) {
                return;
            }
        }
    });
}
