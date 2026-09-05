from __future__ import annotations

import argparse
import signal
import threading

from ..app import AppContext
from ..config import AppConfig


def main() -> int:
    parser = argparse.ArgumentParser(prog="care-debug")
    sub = parser.add_subparsers(dest="command", required=True)
    seed_parser = sub.add_parser("seed")
    seed_parser.add_argument("--days", type=int, default=45)
    seed_parser.add_argument("--profile", default="mixed")
    seed_parser.add_argument("--seed", type=int, default=20260906)
    stream_parser = sub.add_parser("stream")
    stream_parser.add_argument("--profile", default="mixed")
    stream_parser.add_argument("--seed", type=int, default=20260906)
    stream_parser.add_argument("--interval", type=float, default=12.0)
    args = parser.parse_args()

    ctx = AppContext(AppConfig(runtime_mode="debug"), use_stubs=True)
    try:
        if args.command == "seed":
            print(ctx.debug_simulator.generate_history(
                days=args.days, profile=args.profile, seed=args.seed))
            return 0
        print(ctx.debug_simulator.start_stream(
            profile=args.profile, seed=args.seed, interval_sec=args.interval))
        stopped = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stopped.set())
        while not stopped.wait(0.5):
            pass
        ctx.debug_simulator.stop_stream()
        return 0
    finally:
        ctx.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
