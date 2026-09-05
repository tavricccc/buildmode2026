"""Standard-library HTTP + WebSocket server (docs/03_API_AND_FRONTEND.md, docs/04_SETUP_DEPLOY_VERIFY.md).

``ThreadingHTTPServer`` rather than an ASGI stack, for the reason given
throughout: a reviewer clones the repo and runs it, on Windows/WSL,
macOS or Linux, without a wheel build or a virtualenv step. The cost is
that routing and the WebSocket upgrade are written out here; the benefit
is that ``bun start`` has no Python dependency to fail on.

The upgrade path hijacks the connection: ``BaseHTTPRequestHandler`` has
no notion of a protocol switch, so the 101 response is written to the
raw socket and the handler then loops on client frames until close.
"""

from __future__ import annotations

import json
import mimetypes
import re
import socket
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..care_logging import CareLogger
from ..domain.timeutil import iso
from .routes import ROUTES, ApiError, Request
from ..media import ffmpeg
from ..media.browser_source import BrowserMediaSession, BrowserUploadSession
from .ws import OP_BINARY, OP_CLOSE, OP_PING, OP_PONG, OP_TEXT, accept_key, encode_frame, read_frame

MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024


class CareHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], ctx: Any) -> None:
        self.ctx = ctx
        self.tls_enabled = False
        super().__init__(address, CareRequestHandler)
        self._setup_tls()

    def _setup_tls(self) -> None:
        cert = getattr(self.ctx.config, "tls_cert_file", "")
        key = getattr(self.ctx.config, "tls_key_file", "")
        if cert and key and Path(cert).is_file() and Path(key).is_file():
            try:
                import ssl
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(certfile=cert, keyfile=key)
                self.socket = context.wrap_socket(self.socket, server_side=True)
                self.tls_enabled = True
            except Exception:
                self.tls_enabled = False


class CareRequestHandler(BaseHTTPRequestHandler):
    server_version = "CareAgent/5.0"
    protocol_version = "HTTP/1.1"

    # -- plumbing --------------------------------------------------------

    @property
    def ctx(self) -> Any:
        return self.server.ctx  # type: ignore[attr-defined]

    def finish(self) -> None:
        # ThreadingHTTPServer runs one thread per connection and Database
        # keeps a connection per thread, so without this every client
        # connection would leak a SQLite handle for the process's lifetime.
        try:
            super().finish()
        finally:
            try:
                self.server.ctx.db.close()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

    def log_message(self, fmt: str, *args: Any) -> None:
        CareLogger.get().debug("http", fmt % args)

    def log_error(self, fmt: str, *args: Any) -> None:
        try:
            CareLogger.get().warn("http", fmt % args)
        except Exception:  # noqa: BLE001
            pass

    def _send(self, status: int, payload: Any, content_type: str = "application/json") -> None:
        body = (json.dumps(payload, default=str).encode("utf-8")
                if content_type == "application/json" else payload)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # The Dashboard is served from Vite on another port during dev.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ApiError(413, "payload_too_large", f"body exceeds {MAX_BODY_BYTES} bytes")
        raw = self.rfile.read(length)
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError(400, "bad_json", str(exc)) from None
        if not isinstance(parsed, dict):
            raise ApiError(400, "bad_json", "body must be a JSON object")
        return parsed

    # -- verbs -----------------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, b"", "text/plain")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/ws/media":
            self._handle_media_websocket(parsed)
            return
        if parsed.path == "/ws":
            self._handle_websocket()
            return
        self._dispatch("GET", parsed)

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST", urlparse(self.path))

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT", urlparse(self.path))

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE", urlparse(self.path))

    # -- dispatch --------------------------------------------------------

    def _dispatch(self, method: str, parsed: Any) -> None:
        path = parsed.path.rstrip("/") or "/"
        t0 = time.perf_counter()
        try:
            for route_method, pattern, handler in ROUTES:
                if route_method != method:
                    continue
                match = pattern.match(path)
                if match is None:
                    continue
                request = Request(
                    method=method,
                    path=path,
                    query=parse_qs(parsed.query),
                    body=self._body() if method in {"POST", "PUT"} else {},
                    params=match.groupdict(),
                )
                result = handler(self.ctx, request)
                status = result[0]
                latency_ms = int((time.perf_counter() - t0) * 1000)
                level = "debug" if path in {"/api/status", "/api/logs"} else "info"
                CareLogger.get().log(level, "http", f"{method} {path} -> {status} ({latency_ms}ms)")
                if len(result) == 3:
                    status, payload, content_type = result
                    self._send(status, payload, content_type)
                else:
                    status, payload = result
                    self._send(status, payload)
                return

            if method == "GET" and not path.startswith("/api"):
                self._serve_static(path)
                return
            latency_ms = int((time.perf_counter() - t0) * 1000)
            CareLogger.get().warn("http", f"{method} {path} -> 404 not found ({latency_ms}ms)")
            self._send(404, {"error": {"code": "not_found", "message": f"no route for {method} {path}"}})
        except ApiError as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            CareLogger.get().warn("http", f"{method} {path} -> {exc.status} [{exc.code}] {exc.message} ({latency_ms}ms)")
            self._send(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            detail = self.ctx.secrets.redact(f"{type(exc).__name__}: {exc}")
            latency_ms = int((time.perf_counter() - t0) * 1000)
            CareLogger.get().error("http", f"{method} {path} -> 500 {detail} ({latency_ms}ms)")
            self.log_error("unhandled: %s", traceback.format_exc(limit=4))
            self._send(500, {"error": {"code": "internal_error", "message": detail,
                                       "at": iso()}})

    # -- static ----------------------------------------------------------

    def _serve_static(self, path: str) -> None:
        """Serve the built Dashboard; fall back to index.html for SPA routes."""
        root: Path = self.ctx.config.static_dir
        if not root.exists():
            self._send(200, _PLACEHOLDER_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return

        relative = path.lstrip("/") or "index.html"
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            # Path traversal attempt; do not confirm what exists.
            self._send(404, {"error": {"code": "not_found", "message": "not found"}})
            return
        if not candidate.is_file():
            candidate = root / "index.html"
        if not candidate.is_file():
            self._send(404, {"error": {"code": "not_found", "message": "not found"}})
            return

        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/"):
            content_type += "; charset=utf-8"
        self._send(200, candidate.read_bytes(), content_type)

    # -- websocket -------------------------------------------------------

    def _handle_websocket(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        upgrade = (self.headers.get("Upgrade") or "").lower()
        if not key or upgrade != "websocket":
            self._send(400, {"error": {"code": "bad_upgrade", "message": "not a websocket handshake"}})
            return

        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key(key)}\r\n\r\n"
        )
        sock: socket.socket = self.connection
        try:
            sock.sendall(response.encode("ascii"))
        except OSError:
            return

        broadcaster = self.ctx.broadcaster
        broadcaster.add(sock)

        # Replay what this client missed so a reconnect does not need a
        # full REST resync for recent activity (docs/03_API_AND_FRONTEND.md).
        try:
            after = int(self.headers.get("Sec-WebSocket-Protocol") or 0)
        except ValueError:
            after = 0
        for message in broadcaster.backlog(after):
            try:
                sock.sendall(encode_frame(json.dumps(message, default=str).encode("utf-8")))
            except OSError:
                break

        try:
            sock.settimeout(300)
            while True:
                frame = read_frame(sock)
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == OP_CLOSE:
                    break
                if opcode == OP_PING:
                    sock.sendall(encode_frame(payload, OP_PONG))
        except OSError:
            pass
        finally:
            broadcaster.remove(sock)
            self.close_connection = True

    def _handle_media_websocket(self, parsed: Any) -> None:
        """Receive browser MediaRecorder WebM chunks into the pipeline."""
        key = self.headers.get("Sec-WebSocket-Key")
        upgrade = (self.headers.get("Upgrade") or "").lower()
        if not key or upgrade != "websocket":
            self._send(400, {"error": {"code": "bad_upgrade", "message": "not a websocket handshake"}})
            return
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key(key)}\r\n\r\n"
        )
        sock: socket.socket = self.connection
        try:
            sock.sendall(response.encode("ascii"))
        except OSError:
            return

        query = parse_qs(parsed.query)
        camera_id = (query.get("camera_id") or ["browser-camera"])[0][:100]
        media_type = (query.get("media_type") or ["video/webm"])[0][:80]
        mode = (query.get("mode") or [""])[0][:40]
        session_id = f"media-{uuid.uuid4().hex[:16]}"

        if mode == "demo_upload":
            raw_filename = (query.get("filename") or ["upload-video"])[0]
            filename = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(raw_filename).name)[:120] or "upload-video"
            try:
                start_sec = max(0.0, float((query.get("start_sec") or ["0"])[0]))
            except (TypeError, ValueError):
                start_sec = -1.0
            upload_id = f"upload-{uuid.uuid4().hex[:16]}"
            upload_dir = self.ctx.config.data_dir / "uploads"
            incoming_path = upload_dir / "incoming" / f"{upload_id}.bin"
            compressed_path = upload_dir / f"{upload_id}-480p.mp4"
            try:
                upload = BrowserUploadSession(incoming_path, filename, start_sec)
            except (OSError, ValueError) as exc:
                try:
                    sock.sendall(encode_frame(json.dumps({
                        "type": "media.stream.failed",
                        "payload": {"error_code": type(exc).__name__},
                    }).encode("utf-8")))
                except OSError:
                    pass
                self.close_connection = True
                return
            self.ctx.browser_sessions[session_id] = upload
            try:
                sock.sendall(encode_frame(json.dumps({
                    "type": "media.stream.ready", "payload": upload.health(),
                }).encode("utf-8")))
                sock.settimeout(300)
                while True:
                    frame = read_frame(sock)
                    if frame is None:
                        break
                    opcode, payload = frame
                    if opcode == OP_CLOSE:
                        break
                    if opcode == OP_PING:
                        sock.sendall(encode_frame(payload, OP_PONG))
                    elif opcode == OP_BINARY:
                        if len(payload) > MAX_BODY_BYTES:
                            upload.mark_failed("upload_chunk_too_large")
                            break
                        if upload.bytes_received + len(payload) > MAX_UPLOAD_BYTES:
                            upload.mark_failed("upload_too_large")
                            break
                        upload.receive(payload)
                        if upload.chunks_received % 4 == 0:
                            sock.sendall(encode_frame(json.dumps({
                                "type": "media.stream.progress", "payload": upload.health(),
                            }).encode("utf-8")))
                    elif opcode == OP_TEXT:
                        try:
                            msg = json.loads(payload.decode("utf-8", errors="replace"))
                        except Exception:
                            msg = {}
                        if msg.get("type") != "media.upload.complete":
                            continue
                        if start_sec < 0:
                            upload.mark_failed("invalid_start_sec")
                            break
                        try:
                            upload.finish()
                            sock.sendall(encode_frame(json.dumps({
                                "type": "media.stream.processing", "payload": upload.health(),
                            }).encode("utf-8")))
                            ffmpeg.transcode_to_480p(
                                upload.path, compressed_path,
                                start_sec=start_sec, height=480,
                            )
                            upload.mark_processing(str(compressed_path))
                            sock.sendall(encode_frame(json.dumps({
                                "type": "media.stream.progress", "payload": upload.health(),
                            }).encode("utf-8")))
                            self.ctx.start_source(
                                "replay_file", str(compressed_path),
                                width=854, target_height=480, realtime=True,
                            )
                            source = self.ctx.source
                            next_progress = 0.0
                            while source is not None:
                                source_health = source.health()
                                now = time.monotonic()
                                if now >= next_progress:
                                    sock.sendall(encode_frame(json.dumps({
                                        "type": "media.stream.progress",
                                        "payload": {"upload": upload.health(), "source": source_health},
                                    }).encode("utf-8")))
                                    next_progress = now + 1.0
                                if source_health.get("lifecycle") in {"completed", "failed", "stopped"}:
                                    break
                                time.sleep(0.2)
                            final_source = source.health() if source is not None else {}
                            if final_source.get("lifecycle") == "failed":
                                raise RuntimeError(str(final_source.get("error") or "replay_failed"))
                            upload.mark_completed(final_source)
                            sock.sendall(encode_frame(json.dumps({
                                "type": "media.stream.completed",
                                "payload": upload.health(),
                            }).encode("utf-8")))
                        except Exception as exc:  # noqa: BLE001 - report upload failure to UI
                            error_text = f"{type(exc).__name__}: {exc}"
                            upload.mark_failed(error_text)
                            CareLogger.get().error("upload", "video upload processing failed", {
                                "filename": upload.filename,
                                "start_sec": upload.start_sec,
                                "error": error_text,
                            })
                            try:
                                sock.sendall(encode_frame(json.dumps({
                                    "type": "media.stream.failed",
                                    "payload": upload.health(),
                                }).encode("utf-8")))
                            except OSError:
                                pass
                        break
            except OSError:
                pass
            finally:
                self.ctx.browser_sessions.pop(session_id, None)
                upload.close()
                self.close_connection = True
            return

        try:
            session = BrowserMediaSession(
                camera_id, media_type, self.ctx.cascade.ingest,
                fps=self.ctx.policy.cadence.clip_fps,
            )
        except (OSError, ValueError) as exc:
            try:
                sock.sendall(encode_frame(json.dumps({
                    "type": "media.stream.failed",
                    "payload": {"error_code": type(exc).__name__},
                }).encode("utf-8")))
            except OSError:
                pass
            self.close_connection = True
            return
        self.ctx.browser_sessions[session_id] = session
        try:
            sock.sendall(encode_frame(json.dumps({
                "type": "media.stream.ready", "payload": session.health(),
            }).encode("utf-8")))
            sock.settimeout(300)
            while True:
                frame = read_frame(sock)
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == OP_CLOSE:
                    break
                if opcode == OP_PING:
                    sock.sendall(encode_frame(payload, OP_PONG))
                elif opcode == OP_TEXT:
                    try:
                        msg = json.loads(payload.decode("utf-8", errors="replace"))
                    except Exception:
                        msg = {}
                    if msg.get("type") == "media.upload.complete":
                        stats = session.close()
                        sock.sendall(encode_frame(json.dumps({
                            "type": "media.stream.completed", "payload": stats,
                        }).encode("utf-8")))
                        break
                elif opcode == OP_BINARY:
                    if len(payload) > MAX_BODY_BYTES:
                        break
                    session.receive(payload)
                    if session.chunks_received % 4 == 0:
                        sock.sendall(encode_frame(json.dumps({
                            "type": "media.stream.progress", "payload": session.health(),
                        }).encode("utf-8")))
        except OSError:
            pass
        finally:
            self.ctx.browser_sessions.pop(session_id, None)
            session.close()
            self.close_connection = True


_PLACEHOLDER_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Care Agent</title>
<style>body{font:15px/1.6 ui-sans-serif,system-ui,sans-serif;margin:0;padding:3rem;
background:#0f1115;color:#e6e8ee}code{background:#1b1f28;padding:.15rem .4rem;border-radius:4px}
a{color:#8ab4ff}</style></head><body>
<h1>Care Agent — backend is running</h1>
<p>The Dashboard bundle has not been built yet.</p>
<p>Development: <code>cd src/frontend &amp;&amp; bun install &amp;&amp; bun run dev</code>, then open
<a href="http://localhost:5173">http://localhost:5173</a>.</p>
<p>Production bundle: <code>bun run build</code> in <code>src/frontend</code>.</p>
<p>The API is live regardless — try <a href="/api/status">/api/status</a>
or <a href="/api/setup/state">/api/setup/state</a>.</p>
</body></html>"""


def serve(ctx: Any) -> CareHTTPServer:
    server = CareHTTPServer((ctx.config.host, ctx.config.port), ctx)
    thread = threading.Thread(target=server.serve_forever, name="http", daemon=True)
    thread.start()
    return server


def stop(server: CareHTTPServer) -> None:
    """Stop serving *and* release the listening socket.

    ``shutdown()`` alone only breaks the serve_forever loop; the bound
    socket stays open, which leaks a descriptor and makes an immediate
    restart fail with EADDRINUSE.
    """
    server.shutdown()
    server.server_close()
