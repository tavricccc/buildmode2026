#!/usr/bin/env python3
"""Capability probe for an OpenAI-compatible vision endpoint.

Answers the questions docs-implementation-v4/14 records: how many frames
survive one request, whether their order is preserved, whether audio is
actually ingested, whether a video_url part keeps temporal order, and what a
window costs in tokens and latency.

Standard library only; test media is generated with ffmpeg. The key is read
from a file and never printed.

    python3 scripts/probe_provider.py --key-file GMIAPI.txt
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# The GMI edge rejects the default Python-urllib agent with an opaque 403,
# identically for a valid key, an invalid key and no key at all.
USER_AGENT = "Longcare-probe/1.0"
SEGMENTS = {0: "abcdef", 1: "bc", 2: "abged", 3: "abgcd", 4: "fgbc",
            5: "afgcd", 6: "afgecd", 7: "abc", 8: "abcdefg", 9: "abcdfg"}


def digit_sequence(count: int) -> list[int]:
    """Single-digit labels for `count` frames, cycling 0-9 if more are asked for."""
    return [n % 10 for n in range(count)]


def render_digit_jpeg(value: int, path: Path, width: int = 480, height: int = 270) -> None:
    """Draw a seven-segment number, so the model's reading is unambiguous.

    Solid-colour frames are a poor probe: this model misreads them even when
    the frames arrive intact, which makes an ordering failure indistinguishable
    from a recognition failure. Digits are read reliably, so a wrong answer
    means a real transport problem.
    """
    pixels = bytearray(b"\xff" * (width * height * 3))
    digits = [int(c) for c in str(value)]
    seg_w, seg_h, thick, pitch = 90, 170, 18, 110
    origin_x = (width - len(digits) * pitch) // 2
    for index, digit in enumerate(digits):
        ox, oy = origin_x + index * pitch, 50
        boxes = {"a": (ox, oy, seg_w, thick),
                 "g": (ox, oy + seg_h // 2 - thick // 2, seg_w, thick),
                 "d": (ox, oy + seg_h - thick, seg_w, thick),
                 "f": (ox, oy, thick, seg_h // 2),
                 "b": (ox + seg_w - thick, oy, thick, seg_h // 2),
                 "e": (ox, oy + seg_h // 2, thick, seg_h // 2),
                 "c": (ox + seg_w - thick, oy + seg_h // 2, thick, seg_h // 2)}
        for name in SEGMENTS[digit]:
            x, y, bw, bh = boxes[name]
            for yy in range(y, min(y + bh, height)):
                row = yy * width * 3
                for xx in range(x, min(x + bw, width)):
                    i = row + xx * 3
                    pixels[i] = pixels[i + 1] = pixels[i + 2] = 0
    ppm = b"P6\n%d %d\n255\n" % (width, height) + bytes(pixels)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-vcodec", "ppm",
                    "-i", "-", "-frames:v", "1", "-q:v", "2", str(path)],
                   input=ppm, check=True)


def build_media(root: Path, frames: int, fps: float) -> dict[str, Path]:
    """Generate the fixture. Frames are labelled with single digits.

    A two-digit label is a bad fixture: the model reads "10" as "0" often
    enough to look like an ordering failure, which would contaminate exactly
    the measurement this probe exists to make. Single digits are unambiguous,
    so a wrong answer means a real transport problem.
    """
    root.mkdir(parents=True, exist_ok=True)
    paths = {}
    for index, value in enumerate(digit_sequence(frames)):
        p = root / f"n{index:02d}.jpg"
        render_digit_jpeg(value, p)
        paths[f"frame{index}"] = p
    speech = root / "speech.wav"
    aiff = root / "speech.aiff"
    spoken = subprocess.run(["say", "-o", str(aiff), "The code word is pineapple seventeen"],
                            capture_output=True).returncode == 0
    if spoken:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(aiff), "-ar", "16000",
                        "-ac", "1", "-c:a", "pcm_s16le", str(speech)], check=True)
    else:  # no TTS on this host: a tone still proves whether bytes are ingested
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=3", "-ar", "16000", "-ac", "1",
                        "-c:a", "pcm_s16le", str(speech)], check=True)
    paths["audio"], paths["audio_is_speech"] = speech, spoken
    video = root / "window.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", f"{fps:g}", "-f", "image2pipe",
                    "-vcodec", "mjpeg", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-preset", "veryfast", "-crf", "23", "-movflags", "+faststart", str(video)],
                   input=b"".join((root / f"n{i:02d}.jpg").read_bytes() for i in range(frames)),
                   check=True)
    paths["video"] = video
    return paths


class Client:
    def __init__(self, base_url: str, model: str, key: str, timeout: float):
        self.base_url, self.model, self.key, self.timeout = base_url.rstrip("/"), model, key, timeout

    def _request(self, path: str, body: dict | None, user_agent: str | None):
        headers = {"Authorization": f"Bearer {self.key}", "Accept": "application/json"}
        if user_agent:
            headers["User-Agent"] = user_agent
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base_url + path, headers=headers,
                                     method="GET" if body is None else "POST",
                                     data=None if body is None else json.dumps(body).encode())
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.status, json.loads(response.read() or b"{}"), int((time.perf_counter() - started) * 1000)
        except urllib.error.HTTPError as exc:
            return exc.code, {"error": exc.read()[:200].decode(errors="replace")}, int((time.perf_counter() - started) * 1000)
        except Exception as exc:  # network, TLS, timeout
            return 0, {"error": f"{type(exc).__name__}: {exc}"}, int((time.perf_counter() - started) * 1000)

    def models(self, user_agent: str | None = USER_AGENT):
        return self._request("/models", None, user_agent)

    def chat(self, content: list, *, json_mode: bool = True, user_agent: str | None = USER_AGENT):
        body = {"model": self.model, "messages": [{"role": "user", "content": content}],
                "temperature": 0.0, "max_tokens": 300}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        status, payload, ms = self._request("/chat/completions", body, user_agent)
        text = ""
        if status == 200:
            text = (payload.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        return status, text, (payload.get("usage") or {}).get("prompt_tokens"), ms, payload


b64 = lambda p: base64.b64encode(Path(p).read_bytes()).decode()
image_part = lambda p: {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64(p)}}


def parse_json(text: str):
    body = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(body)
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.getenv("FLOW_MODEL_BASE_URL") or "https://api.gmi-serving.com/v1")
    ap.add_argument("--model", default=os.getenv("FLOW_MODEL_ID") or "MiniMaxAI/MiniMax-M3")
    ap.add_argument("--key-file", default=os.getenv("FLOW_MODEL_API_KEY_FILE") or "GMIAPI.txt")
    ap.add_argument("--frames", type=int, default=10)
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--repeats", type=int, default=3,
                    help="repeats for the ordering checks; a wire format can pass once by luck")
    ap.add_argument("--keep-media", action="store_true", help="keep the generated test media")
    args = ap.parse_args()

    key_path = Path(args.key_file)
    if not key_path.is_file():
        print(f"key file not found: {key_path}", file=sys.stderr)
        return 2
    key = key_path.read_text(encoding="utf-8").strip()
    if not key:
        print(f"key file is empty: {key_path}", file=sys.stderr)
        return 2

    client = Client(args.base_url, args.model, key, args.timeout)
    results: list[tuple[str, bool | None, str]] = []

    def record(name, ok, detail):
        results.append((name, ok, detail))
        mark = "PASS" if ok else ("INFO" if ok is None else "FAIL")
        print(f"  {mark}  {name}: {detail}", flush=True)

    workdir = Path(tempfile.mkdtemp(prefix="provider-probe-"))
    print(f"\n=== provider probe ===\n  endpoint : {args.base_url}\n  model    : {args.model}"
          f"\n  key      : {key_path} (…{key[-4:]})\n  media    : {workdir}\n")
    try:
        media = build_media(workdir, args.frames, args.fps)
        expected = digit_sequence(args.frames)

        print("[1] endpoint")
        status, payload, ms = client.models()
        ids = [m.get("id", "") for m in payload.get("data", [])] if status == 200 else []
        record("models listing", status == 200,
               f"HTTP {status}, {len(ids)} models, {ms}ms" +
               (f", model present: {any(args.model in i for i in ids)}" if ids else f" | {str(payload)[:120]}"))

        # A default urllib agent is rejected identically to a bad key on some edges.
        status_noua, _, _ = client._request("/models", None, None)
        record("default User-Agent accepted", status_noua == 200,
               f"HTTP {status_noua} without an explicit User-Agent"
               + ("" if status_noua == 200 else " — client MUST set one; this looks like an auth error but is not"))

        def ordering_trial(content):
            """One ordering attempt: returns (http status, digits, tokens, latency)."""
            status, text, tokens, ms, _ = client.chat(content)
            got = (parse_json(text) or {}).get("digits") if status == 200 else None
            return status, ([str(x) for x in got] if got else None), tokens, ms

        want = [str(x) for x in expected]
        window_ms = (args.frames / args.fps) * 1000
        prompt = ('依序給你 %d 張圖,每張中央有一個數字。只輸出 JSON:{"digits":[<依序列出>]}' % args.frames)
        frame_content = [{"type": "text", "text": prompt}] + [image_part(media[f"frame{i}"]) for i in range(args.frames)]

        print(f"\n[2] {args.frames} frames: order and completeness ({args.repeats} repeats)")
        ordered = complete = 0
        latencies, token_counts, first_bad = [], [], None
        for _ in range(args.repeats):
            status, got, tokens, ms = ordering_trial(frame_content)
            if status != 200:
                record("frames accepted", False, f"HTTP {status}")
                break
            latencies.append(ms)
            if tokens:
                token_counts.append(tokens)
            if got and len(got) == args.frames:
                complete += 1
            if got == want:
                ordered += 1
            elif first_bad is None:
                first_bad = got
        else:
            record("frames accepted", True,
                   f"{args.repeats}/{args.repeats} HTTP 200, {min(latencies)}-{max(latencies)}ms, "
                   f"prompt_tokens~{sum(token_counts)//len(token_counts) if token_counts else '?'}")
            record("frame order preserved", ordered == args.repeats,
                   f"{ordered}/{args.repeats} exact" + (f"; first mismatch {first_bad}" if first_bad else ""))
            record("no silent truncation", complete == args.repeats,
                   f"{complete}/{args.repeats} returned all {args.frames} frames")
            if token_counts:
                per_frame = sum(token_counts) // len(token_counts) // args.frames
                ordered_lat = sorted(latencies)
                median = ordered_lat[len(ordered_lat) // 2]
                record("latency under window", max(latencies) < window_ms,
                       f"median {median}ms, worst {max(latencies)}ms vs {window_ms/1000:.1f}s window; "
                       f"~{per_frame} tokens/frame"
                       + ("" if max(latencies) < window_ms else
                          " — a window slower than its own length makes the loop fall behind"))

        print("\n[3] audio ingestion (token delta is the evidence)")
        ask = [{"type": "text", "text": '只輸出 JSON:{"heard":"<spoken words, or nothing>"}'}]
        _, _, base_tokens, _, _ = client.chat(ask)
        deltas = {}
        for label, part in (("audio_url", {"type": "audio_url", "audio_url": {"url": "data:audio/wav;base64," + b64(media["audio"])}}),
                            ("input_audio", {"type": "input_audio", "input_audio": {"data": b64(media["audio"]), "format": "wav"}}),
                            ("corrupt bytes", {"type": "audio_url", "audio_url": {"url": "data:audio/wav;base64," + base64.b64encode(os.urandom(60000)).decode()}})):
            status, text, tokens, ms, _ = client.chat(ask + [part])
            deltas[label] = None if (tokens is None or base_tokens is None) else tokens - base_tokens
            record(f"audio via {label}", None, f"HTTP {status}, prompt_tokens={tokens} (baseline {base_tokens}, delta {deltas[label]}) | {text[:60]!r}")
        ingested = any(d for d in deltas.values() if d)
        record("audio reaches the model", ingested,
               "at least one format added prompt tokens" if ingested else
               "no format changed prompt_tokens — audio is dropped before the model, including corrupt bytes (no error)")
        if not media["audio_is_speech"]:
            record("speech fixture", None, "`say` unavailable: a tone was used, which still proves ingestion but not transcription")

        print(f"\n[4] video_url wire format ({args.repeats} repeats)")
        # This format has been seen to pass once and fail the next five times on
        # the same file, so a single trial is not evidence.
        video_content = [{"type": "text", "text": '影片中依序出現數字。只輸出 JSON:{"digits":[<依序列出>]}'},
                         {"type": "video_url", "video_url": {"url": "data:video/mp4;base64," + b64(media["video"])}}]
        vok = vaccepted = 0
        vlat, vbad = [], []
        for _ in range(args.repeats):
            status, got, tokens, ms = ordering_trial(video_content)
            if status != 200:
                continue
            vaccepted += 1
            vlat.append(ms)
            if got == want:
                vok += 1
            else:
                vbad.append(got)
        record("video accepted", vaccepted == args.repeats,
               f"{vaccepted}/{args.repeats} HTTP 200" + (f", {min(vlat)}-{max(vlat)}ms" if vlat else ""))
        if vaccepted:
            record("video order preserved", vok == args.repeats,
                   f"{vok}/{vaccepted} exact" + (f"; failures {vbad[:2]}" if vbad else ""))

        print("\n[5] json_object stability (5 calls)")
        ok = 0
        for _ in range(5):
            status, text, _, _, _ = client.chat([{"type": "text", "text": '只輸出 JSON:{"posture":"standing"}'},
                                                 image_part(media["frame0"])])
            if status == 200 and parse_json(text) is not None:
                ok += 1
        record("json_object parseable", ok == 5, f"{ok}/5")

        print("\n=== summary ===")
        for name, ok, _ in results:
            print(f"  {'-' if ok is None else ('OK' if ok else 'XX')}  {name}")
        failed = [n for n, ok, _ in results if ok is False]
        if failed:
            print(f"\n  {len(failed)} check(s) failed: {', '.join(failed)}")
        return 1 if failed else 0
    finally:
        if args.keep_media:
            print(f"\n  media kept at {workdir}")
        else:
            for f in workdir.glob("*"):
                f.unlink(missing_ok=True)
            workdir.rmdir()


if __name__ == "__main__":
    sys.exit(main())
