"""rlviz stream format v1: a MessagePack header map followed by frame maps.

Files (``*.rlviz``) are the same stream compressed with zstd. The full description is in
``docs/rlviz_format.md``; the Rust reader is ``src/rlviz/format.rs``. Readers ignore keys they do not
know, so new optional fields don't need a version bump.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, BinaryIO, Iterator

import msgpack
import zstandard

FORMAT_NAME = "rlviz"
FORMAT_VERSION = 1

GAME_MODES = ("soccar", "hoops", "heatseeker", "snowday", "dropshot", "void")

Header = dict[str, Any]
Frame = dict[str, Any]


def make_header(
    game_mode: str,
    *,
    tick_rate: float = 120.0,
    pads: list[dict] | None = None,
    cars: list[dict] | None = None,
    meta: dict | None = None,
) -> Header:
    """``pads``: ``[{"pos": [x, y, z], "big": bool}]``.
    ``cars``: ``[{"id", "team" (0 blue, 1 orange), "name", "config"}]``, see ``sim.car_config``."""
    if game_mode not in GAME_MODES:
        raise ValueError(f"unknown game mode {game_mode!r}")
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "game_mode": game_mode,
        "tick_rate": float(tick_rate),
        "pads": pads or [],
        "cars": cars or [],
        "meta": meta or {},
    }


def _packer() -> msgpack.Packer:
    # Single floats halve the size; positions in uu don't need more.
    return msgpack.Packer(use_single_float=True)


class StreamWriter:
    """Writes a header and frames to a binary stream (socket file, zstd writer, ...)."""

    def __init__(self, out: BinaryIO, header: Header):
        self._out = out
        self._packer = _packer()
        self.header = header
        self._out.write(self._packer.pack(header))

    def write(self, frame: Frame) -> None:
        self._out.write(self._packer.pack(frame))

    def flush(self) -> None:
        self._out.flush()


class ReplayWriter(StreamWriter):
    """A ``.rlviz`` file: the stream compressed with zstd."""

    def __init__(self, path: str | Path, header: Header, level: int = 3):
        self.path = Path(path)
        self._file = open(self.path, "wb")
        self._zstd = zstandard.ZstdCompressor(level=level).stream_writer(self._file)
        super().__init__(self._zstd, header)

    def close(self) -> None:
        self._zstd.close()  # also closes the file

    def __enter__(self) -> ReplayWriter:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _unpacker(stream: BinaryIO) -> msgpack.Unpacker:
    return msgpack.Unpacker(stream, raw=False, strict_map_key=False, max_buffer_size=1 << 30)


def read_stream(stream: BinaryIO) -> tuple[Header, Iterator[Frame]]:
    unpacker = _unpacker(stream)
    header = next(unpacker)
    if header.get("format") != FORMAT_NAME or header.get("version", 0) > FORMAT_VERSION:
        raise ValueError(f"not an rlviz v{FORMAT_VERSION} stream: {header.get('format')} v{header.get('version')}")
    return header, unpacker


def read_replay(path: str | Path) -> tuple[Header, list[Frame]]:
    """Loads a whole ``.rlviz`` file."""
    with open(path, "rb") as f:
        raw = zstandard.ZstdDecompressor().stream_reader(f).read()
    header, frames = read_stream(io.BytesIO(raw))
    return header, list(frames)
