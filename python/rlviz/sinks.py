"""Where frames go: a live viewer (TCP) or a replay file."""

from __future__ import annotations

import socket
import time
from pathlib import Path

from .format import Frame, Header, ReplayWriter, StreamWriter

DEFAULT_PORT = 45300


class LiveSink:
    """Streams to a running viewer (``rlviser`` listens on 127.0.0.1:45300).

    With ``realtime`` the sink sleeps so frames arrive at game speed (times ``speed``); otherwise
    they are sent as fast as they come and the viewer's timeline can be scrubbed afterwards.
    """

    def __init__(self, header: Header, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 realtime: bool = True, speed: float = 1.0):
        self._sock = socket.create_connection((host, port))
        self._file = self._sock.makefile("wb")
        self._writer = StreamWriter(self._file, header)
        self._tick_rate = header["tick_rate"]
        self.realtime = realtime
        self.speed = speed
        self._t0: float | None = None
        self._tick0 = 0

    def write(self, frame: Frame) -> None:
        try:
            self._writer.write(frame)
            self._writer.flush()
        except (BrokenPipeError, ConnectionResetError) as e:
            raise ConnectionError("the viewer closed the connection (was rlviser closed or restarted?)") from e
        if not self.realtime:
            return
        if self._t0 is None:
            self._t0, self._tick0 = time.perf_counter(), frame["tick"]
            return
        due = self._t0 + (frame["tick"] - self._tick0) / (self._tick_rate * self.speed)
        delay = due - time.perf_counter()
        if delay > 0:
            time.sleep(delay)

    def close(self) -> None:
        try:
            self._file.close()
        except OSError:
            pass
        finally:
            self._sock.close()


class FileSink:
    """Writes a ``.rlviz`` replay."""

    def __init__(self, header: Header, path: str | Path):
        self._writer = ReplayWriter(path, header)
        self.path = self._writer.path

    def write(self, frame: Frame) -> None:
        self._writer.write(frame)

    def close(self) -> None:
        self._writer.close()
