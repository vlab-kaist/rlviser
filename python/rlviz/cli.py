"""``rlviz`` command line.

    rlviz demo [--live] [--out game.rlviz] [--seconds 60] [--mode soccar] [--layers ...]
    rlviz annotate in.rlviz out.rlviz [--layers ...]
    rlviz info game.rlviz
    rlviz video plays.rlviz plays.mp4 [--speed 0.35] [--labels "alone|vs bot 1"]
"""

from __future__ import annotations

import argparse
import sys
import time

from .format import ReplayWriter, read_replay
from .layers import DEFAULT_LAYERS, LAYERS, Annotator, make_layers
from .sinks import DEFAULT_PORT, FileSink, LiveSink


def _layer_names(arg: str | None) -> list[str]:
    if arg is None:
        return list(DEFAULT_LAYERS)
    return [n for n in arg.split(",") if n]


def cmd_demo(args) -> None:
    from . import sim

    arena = sim.make_arena(args.mode, args.blue, args.orange, seed=args.seed)
    header = sim.arena_header(arena, meta={"source": "rlviz demo", "created": time.strftime("%Y-%m-%dT%H:%M:%S")})
    agents = {car.id: sim.ball_chase_agent() for car in arena.get_cars()}
    sinks = []
    if args.live:
        sinks.append(LiveSink(header, port=args.port, realtime=not args.fast, speed=args.speed))
    if args.out:
        sinks.append(FileSink(header, args.out))
    if not sinks:
        sys.exit("nothing to do: pass --live and/or --out FILE")
    try:
        n = sim.run(arena, agents, sinks, seconds=args.seconds, header=header,
                    layers=make_layers(_layer_names(args.layers)), seed=args.seed)
    finally:
        for sink in sinks:
            sink.close()
    print(f"{n} frames" + (f" -> {args.out}" if args.out else ""))


def cmd_annotate(args) -> None:
    header, frames = read_replay(args.input)
    if args.module:
        __import__(args.module)  # lets a module register extra layers in LAYERS
    annotate = Annotator(header, make_layers(_layer_names(args.layers)))
    if args.clear:
        for frame in frames:
            frame.pop("draw", None)
    if any(name == "ball_prediction" for name in _layer_names(args.layers)):
        from . import sim

        sim.init()
    with ReplayWriter(args.output, header) as out:
        for frame in frames:
            out.write(annotate(frame))
    print(f"{len(frames)} frames -> {args.output}")


def cmd_info(args) -> None:
    header, frames = read_replay(args.input)
    print({k: v for k, v in header.items() if k not in ("pads", "cars")})
    for car in header.get("cars", []):
        print(f"  car {car['id']}: team {car['team']} {car.get('name', '')}")
    if frames:
        ticks = frames[-1]["tick"] - frames[0]["tick"]
        groups = sorted({g["name"] for f in frames for g in f.get("draw", [])})
        print(f"{len(frames)} frames, ticks {frames[0]['tick']}..{frames[-1]['tick']} "
              f"({ticks / header['tick_rate']:.1f} s), draw groups: {groups}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="rlviz")
    sub = parser.add_subparsers(dest="cmd", required=True)
    layers_help = f"comma-separated layers (default {','.join(DEFAULT_LAYERS)}; available {','.join(LAYERS)})"

    p = sub.add_parser("demo", help="simulate scripted ball chasers")
    p.add_argument("--live", action="store_true", help="stream to a running viewer")
    p.add_argument("--fast", action="store_true", help="with --live, don't pace to real time")
    p.add_argument("--speed", type=float, default=1.0, help="with --live, game speed")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--out", help="write a .rlviz replay")
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--mode", default="soccar")
    p.add_argument("--blue", type=int, default=1)
    p.add_argument("--orange", type=int, default=1)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--layers", help=layers_help)
    p.set_defaults(fn=cmd_demo)

    p = sub.add_parser("annotate", help="recompute debug layers on a replay")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--layers", help=layers_help)
    p.add_argument("--clear", action="store_true", help="drop all existing draw groups first")
    p.add_argument("--module", help="import this module first (to register custom layers)")
    p.set_defaults(fn=cmd_annotate)

    p = sub.add_parser("info", help="summarize a replay")
    p.add_argument("input")
    p.set_defaults(fn=cmd_info)

    from . import video

    p = sub.add_parser("video", help="record a replay's runs (split at tick gaps) into one tiled mp4")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--speed", type=float, default=0.35, help="game seconds per video second")
    p.add_argument("--follow", default="-1300,-1700,750", help="camera offset from the ball (X,Y,Z)")
    p.add_argument("--follow-team", type=int, help="also keep this team's car nearest the ball in view")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--labels", help="'|'-separated label per run (default 'run k/n')")
    p.add_argument("--viewer", default=str(video.VIEWER))
    p.add_argument("--display", help="X display to render on (default $DISPLAY, else :99)")
    p.set_defaults(fn=video.main)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
