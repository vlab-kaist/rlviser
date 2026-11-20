"""Render a replay that holds several runs ("flights") of the same start into one tiled video.

A replay is split wherever the tick does not advance by exactly one: writers put the runs one after
the other with a gap of ticks between them. Each run is recorded on its own by the viewer (headless,
``--from``/``--to``, ball-following camera, optionally also framing the nearest car of a team, slow
motion) and the clips are tiled side by side
(2 runs) or in a grid of two columns, all starting together, each holding its last frame until the
longest one ends. A replay without gaps gives a single clip.

    rlviz video plays.rlviz plays.mp4 --speed 0.35
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
           follow_team: int | None = None, fps: int = 30, labels: list[str] | None = None, viewer: str | Path = VIEWER,
           display: str | None = None) -> int:
    """Record every run of ``replay`` and tile them into ``output``. Returns the number of runs."""
    with tempfile.TemporaryDirectory() as tmp:
        return _render(replay, Path(output), Path(tmp), speed=speed, follow=follow, follow_team=follow_team, fps=fps,
                       labels=labels, viewer=viewer, display=display)


def _render(replay, output: Path, clip_dir: Path, *, speed, follow, follow_team, fps, labels, viewer,
            display) -> int:
    rate, spans = runs(replay)
    env = {**os.environ, "DISPLAY": display or os.environ.get("DISPLAY", ":99")}
    clips = []
    for k, (a, b) in enumerate(spans):
        clip = clip_dir / f"run{k}.mp4"
        cmd = [str(viewer), "34255", "45244", "--rlviz-port", "45301", "--replay", str(replay),
               "--from", f"{a / rate:.4f}", "--to", f"{b / rate:.4f}", "--record-speed", str(speed),
               "--follow", follow, *(["--follow-team", str(follow_team)] if follow_team is not None else []), "--record", str(clip), "--fps", str(fps), "--window", f"{CLIP_W}x{CLIP_H}"]
        with open(clip_dir / f"run{k}.log", "w") as log:
            subprocess.run(cmd, env=env, stdout=log, stderr=log, timeout=900, check=True)
        clips.append(clip)

    labels = labels or ([f"run {k + 1}/{len(clips)}" for k in range(len(clips))] if len(clips) > 1 else [""])
    longest = max(_duration(c) for c in clips) + 1.0
    font = subprocess.check_output(["fc-match", "-f", "%{file}", "monospace"], text=True)
    inputs, chains = [], []
    for k, clip in enumerate(clips):
        inputs += ["-i", str(clip)]
        text = labels[k].replace("\\", "\\\\").replace("'", "’").replace(":", "\\:")
        draw = (f",drawtext=fontfile={font}:text='{text}':x=w-tw-20:y=h-th-20:fontsize=26:fontcolor=white:"
                "box=1:boxcolor=black@0.5") if text else ""
        chains.append(f"[{k}]fps={fps},tpad=stop_mode=clone:stop_duration={longest}{draw}[v{k}]")
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


def main(args) -> None:
    if not shutil.which("ffmpeg"):
        raise SystemExit("needs ffmpeg")
    labels = args.labels.split("|") if args.labels else None
    n = render(args.input, args.output, speed=args.speed, follow=args.follow, follow_team=args.follow_team, fps=args.fps, labels=labels,
                   viewer=args.viewer, display=args.display)
    print(f"{n} runs -> {args.output}")
