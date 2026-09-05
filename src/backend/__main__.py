"""Entry point: ``python3 -m backend`` (docs/04_SETUP_DEPLOY_VERIFY.md, driven by ``bun start``)."""

from __future__ import annotations

import argparse
import signal
import sys
import threading

from .api.server import serve, stop
from .app import AppContext
from .config import AppConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backend", description="Care Agent backend")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--source", default=None,
                        help="replay scenario id to start immediately (e.g. 'fall')")
    parser.add_argument("--rtsp", default=None, help="RTSP URI to start immediately")
    parser.add_argument("--stubs", action="store_true",
                        help="force the offline stub backends even if keys are configured")
    parser.add_argument("--debug", action="store_true",
                        help="use the isolated debug runtime and simulation API")
    args = parser.parse_args(argv)

    config = AppConfig(runtime_mode="debug" if args.debug else "production")
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port

    ctx = AppContext(config, use_stubs=True if args.stubs else None)
    server = serve(ctx)
    print(f"[care-agent] http://{config.host}:{config.port}  "
          f"mode={config.runtime_mode}  config={ctx.policy.version}  db={config.db_path}", flush=True)

    if args.rtsp:
        ctx.start_source("rtsp", args.rtsp)
        print(f"[care-agent] RTSP source started", flush=True)
    elif args.source:
        ctx.start_source("replay_scenario", args.source)
        print(f"[care-agent] replay scenario '{args.source}' started", flush=True)

    stopping = threading.Event()

    def shutdown(signum: int, frame: object) -> None:
        stopping.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, shutdown)

    try:
        while not stopping.is_set():
            stopping.wait(0.5)
    finally:
        print("[care-agent] shutting down", flush=True)
        stop(server)
        ctx.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
