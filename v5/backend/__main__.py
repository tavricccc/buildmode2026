"""Entry point: ``python3 -m backend`` (v5 04, driven by ``bun start``)."""

from __future__ import annotations

import argparse
import signal
import sys
import threading

import os

from .api.server import serve, stop
from .app import AppContext
from .config import AppConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backend", description="Care Agent v5 backend")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--source", default=None,
                        help="replay scenario id to start immediately (e.g. 'fall')")
    parser.add_argument("--rtsp", default=None, help="RTSP URI to start immediately")
    parser.add_argument("--tls", action="store_true", help="enable HTTPS with LAN certificates")
    parser.add_argument("--no-tls", action="store_true", help="force plain HTTP")
    parser.add_argument("--stubs", action="store_true",
                        help="force the offline stub backends even if keys are configured")
    args = parser.parse_args(argv)

    config = AppConfig()
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port

    if not args.no_tls:
        if args.tls or args.port == 8200 or os.environ.get("CARE_TLS_CERT_FILE"):
            from pathlib import Path
            cert = Path("d:/Longcare/certs/lan.crt")
            key = Path("d:/Longcare/certs/lan.key")
            if cert.is_file() and key.is_file():
                config.tls_cert_file = str(cert)
                config.tls_key_file = str(key)

    ctx = AppContext(config, use_stubs=True if args.stubs else None)
    server = serve(ctx)
    scheme = "https" if server.tls_enabled else "http"
    print(f"[care-agent-v5] {scheme}://{config.host}:{config.port}  "
          f"config={ctx.policy.version}  db={config.db_path}", flush=True)

    if args.rtsp:
        ctx.start_source("rtsp", args.rtsp)
        print(f"[care-agent-v5] RTSP source started", flush=True)
    elif args.source:
        ctx.start_source("replay_scenario", args.source)
        print(f"[care-agent-v5] replay scenario '{args.source}' started", flush=True)

    stopping = threading.Event()

    def shutdown(signum: int, frame: object) -> None:
        stopping.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, shutdown)

    try:
        while not stopping.is_set():
            stopping.wait(0.5)
    finally:
        print("[care-agent-v5] shutting down", flush=True)
        stop(server)
        ctx.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
