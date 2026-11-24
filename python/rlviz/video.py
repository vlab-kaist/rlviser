"""Render a replay that holds several runs ("flights") of the same start into one tiled video.

A replay is split wherever the tick does not advance by exactly one: writers put the runs one after
the other with a gap of ticks between them. Each run is recorded on its own by the viewer (headless,
``--from``/``--to``, ball-following camera, optionally also framing the nearest car of a team, slow
motion) and the clips are tiled side by side
(2 runs) or in a grid of two columns, all starting together, each holding its last frame until the
longest one ends. A replay without gaps gives a single clip. ``sequence`` plays the runs one after the
other instead (for many short runs, e.g. 20 episodes).

Slow motion around moments: give ``slow_ticks`` (ticks relative to the replay start) and the runs are
recorded at ``slow_speed``, then sped up to ``speed`` outside ``slow_window`` seconds around each tick.
``--slow-wavedash`` takes the landings found by the ``wavedash`` layer.

    rlviz video plays.rlviz plays.mp4 --speed 0.35
    rlviz video episodes.rlviz episodes.mp4 --sequence --speed 1 --slow-wavedash --slow-speed 0.25
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .format import read_replay

VIEWER = Path(__file__).resolve().parents[2] / "target" / "release" / "rlviser"
CLIP_W, CLIP_H = 960, 540


def runs(path: str | Path) -> tuple[float, list[tuple[int, int]]]:
    """``(tick_rate, [(first tick, last tick)])`` of the runs in a replay, ticks relative to its start.
    A run's last frame is left out when it only clears the draw groups, so the held end of the clip
    keeps the drawings."""
    header, frames = read_replay(path)
    ticks = [f["tick"] for f in frames]
    out, start = [], 0
    for i in range(1, len(ticks) + 1):
        if i == len(ticks) or ticks[i] != ticks[i - 1] + 1:
            draw = frames[i - 1].get("draw")
            end = i - 2 if i - 1 > start and draw and not any(g["prims"] for g in draw) else i - 1
            out.append((ticks[start] - ticks[0], ticks[end] - ticks[0]))
            start = i
    return header["tick_rate"], out


def _duration(path: Path) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]))


def render(replay: str | Path, output: str | Path, *, speed: float = 0.35, follow: str = "-1300,-1700,750",
           follow_team: int | None = None, follow_car: int | None = None, fps: int = 30, labels: list[str] | None = None, viewer: str | Path = VIEWER,
           display: str | None = None, sequence: bool = False, slow_ticks: list[int] | None = None,
           slow_speed: float = 0.25, slow_window: float = 0.3) -> int:
    """Record every run of ``replay`` and tile them (or with ``sequence``, chain them) into ``output``.
    Returns the number of runs."""
    with tempfile.TemporaryDirectory() as tmp:
        return _render(replay, Path(output), Path(tmp), speed=speed, follow=follow, follow_team=follow_team, follow_car=follow_car,
                       fps=fps, labels=labels, viewer=viewer, display=display, sequence=sequence, slow_ticks=slow_ticks,
                       slow_speed=slow_speed, slow_window=slow_window)


def _retime(clip: Path, out: Path, start: float, moments: list[float], rec_speed: float, speed: float,
            window: float, fps: int, font: str) -> None:
    """``clip`` was recorded at ``rec_speed`` from replay second ``start``: keep it slow within ``window``
    of each moment (replay seconds) and speed the rest up to ``speed``."""
    dur = _duration(clip)
    slow = []
    for m in sorted(moments):
        a, b = max(0.0, (m - window - start) / rec_speed), min(dur, (m + window - start) / rec_speed)
        if b <= a:
            continue
        if slow and a <= slow[-1][1]:
            slow[-1] = (slow[-1][0], b)
        else:
            slow.append((a, b))
    segs, t = [], 0.0
    for a, b in slow:
        if a > t:
            segs.append((t, a, False))
        segs.append((a, b, True))
        t = b
    if t < dur:
        segs.append((t, dur, False))
    chains = []
    for k, (a, b, is_slow) in enumerate(segs):
        f = 1.0 if is_slow else rec_speed / speed
        mark = (f",drawtext=fontfile={font}:text='slow {rec_speed / speed:g}x':x=(w-tw)/2:y=60:fontsize=30:"
                "fontcolor=yellow:box=1:boxcolor=black@0.5") if is_slow else ""
        chains.append(f"[0]trim={a:.3f}:{b:.3f},setpts=(PTS-STARTPTS)*{f:.4f}{mark}[s{k}]")
    cells = "".join(f"[s{k}]" for k in range(len(segs)))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(clip), "-filter_complex",
                    ";".join(chains) + f";{cells}concat=n={len(segs)}:v=1:a=0,fps={fps}[out]", "-map", "[out]",
                    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(out)], check=True)


def _render(replay, output: Path, clip_dir: Path, *, speed, follow, follow_team, fps, follow_car=None, labels, viewer,
            display, sequence=False, slow_ticks=None, slow_speed=0.25, slow_window=0.3) -> int:
    rate, spans = runs(replay)
    font = subprocess.check_output(["fc-match", "-f", "%{file}", "monospace"], text=True)
    rec_speed = slow_speed if slow_ticks else speed
    env = {**os.environ, "DISPLAY": display or os.environ.get("DISPLAY", ":99")}
    clips = []
    for k, (a, b) in enumerate(spans):
        clip = clip_dir / f"run{k}.mp4"
        cmd = [str(viewer), "34255", "45244", "--rlviz-port", "45301", "--replay", str(replay),
               "--from", f"{a / rate:.4f}", "--to", f"{b / rate:.4f}", "--record-speed", str(rec_speed),
               "--follow", follow, *(["--follow-team", str(follow_team)] if follow_team is not None else []),
               *(["--follow-car", str(follow_car)] if follow_car is not None else []), "--record", str(clip), "--fps", str(fps), "--window", f"{CLIP_W}x{CLIP_H}"]
        with open(clip_dir / f"run{k}.log", "w") as log:
            subprocess.run(cmd, env=env, stdout=log, stderr=log, timeout=900, check=True)
        if slow_ticks:
            fast = clip_dir / f"run{k}_retimed.mp4"
            _retime(clip, fast, a / rate, [t / rate for t in slow_ticks if a <= t <= b], rec_speed, speed,
                    slow_window, fps, font)
            clip = fast
        clips.append(clip)

    labels = labels or ([f"run {k + 1}/{len(clips)}" for k in range(len(clips))] if len(clips) > 1 else [""])
    if sequence:
        _chain(clips, labels, output, fps, font)
        return len(clips)
    longest = max(_duration(c) for c in clips) + 1.0
    inputs, chains = [], []
    for k, clip in enumerate(clips):
        inputs += ["-i", str(clip)]
        chains.append(f"[{k}]fps={fps},tpad=stop_mode=clone:stop_duration={longest}{_label(labels[k], font)}[v{k}]")
    n = len(clips)
    if n % 2 and n > 1:  # empty cell to fill the grid
        inputs += ["-f", "lavfi", "-i", f"color=c=black:s={CLIP_W}x{CLIP_H}:r={fps}"]
        chains.append(f"[{n}]null[v{n}]")
        n += 1
    cells = "".join(f"[v{k}]" for k in range(n))
    if n == 1:
        tile = f"{cells}null[out]"
    elif n == 2:
        tile = f"{cells}hstack[out]"
    else:
        layout = "|".join(f"{(k % 2) * CLIP_W}_{(k // 2) * CLIP_H}" for k in range(n))
        tile = f"{cells}xstack=inputs={n}:layout={layout}[out]"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(chains + [tile]),
                    "-map", "[out]", "-t", f"{longest:.2f}", "-c:v", "libx264", "-crf", "22", "-pix_fmt", "yuv420p",
                    str(output)], check=True)
    return len(clips)


def _label(text: str, font: str) -> str:
    text = text.replace("\\", "\\\\").replace("'", "’").replace(":", "\\:")
    return (f",drawtext=fontfile={font}:text='{text}':x=w-tw-20:y=h-th-20:fontsize=26:fontcolor=white:"
            "box=1:boxcolor=black@0.5") if text else ""


def _chain(clips: list[Path], labels: list[str], output: Path, fps: int, font: str) -> None:
    """The clips one after the other, each holding its last frame for half a second."""
    inputs, chains = [], []
    for k, clip in enumerate(clips):
        inputs += ["-i", str(clip)]
        chains.append(f"[{k}]fps={fps},tpad=stop_mode=clone:stop_duration=0.5{_label(labels[k], font)},setsar=1[v{k}]")
    cells = "".join(f"[v{k}]" for k in range(len(clips)))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex",
                    ";".join(chains) + f";{cells}concat=n={len(clips)}:v=1:a=0[out]", "-map", "[out]",
                    "-c:v", "libx264", "-crf", "22", "-pix_fmt", "yuv420p", str(output)], check=True)


def main(args) -> None:
    if not shutil.which("ffmpeg"):
        raise SystemExit("needs ffmpeg")
    labels = args.labels.split("|") if args.labels else None
    slow = None
    if args.slow_wavedash:
        from .layers.wavedash import landings

        header, frames = read_replay(args.input)
        slow = [land.tick - frames[0]["tick"] for land in landings(header, frames) if land.dodge_tick is not None]
    n = render(args.input, args.output, speed=args.speed, follow=args.follow, follow_team=args.follow_team, follow_car=args.follow_car,
               fps=args.fps, labels=labels, viewer=args.viewer, display=args.display, sequence=args.sequence, slow_ticks=slow,
               slow_speed=args.slow_speed, slow_window=args.slow_window)
    print(f"{n} runs -> {args.output}")
