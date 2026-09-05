from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ..media import ffmpeg
from ..media.browser_source import BrowserUploadSession


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
class TestVideoUpload(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="care-upload-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_upload_is_transcoded_to_480p_from_requested_start(self) -> None:
        source = self.tmp / "source.mp4"
        output = self.tmp / "uploads" / "upload-480p.mp4"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=4",
            "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=16000",
            "-t", "2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(source),
        ], check=True, timeout=30)

        result = ffmpeg.transcode_to_480p(source, output, start_sec=0.5, height=480)
        self.assertEqual(result["height"], 480)
        self.assertTrue(output.is_file())

        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(output),
        ], capture_output=True, text=True, check=True, timeout=15)
        metadata = json.loads(probe.stdout)
        video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
        self.assertEqual(video["height"], 480)
        self.assertLess(float(metadata["format"]["duration"]), 1.7)

    def test_upload_session_persists_chunks_until_transcode(self) -> None:
        incoming = self.tmp / "incoming" / "upload.bin"
        session = BrowserUploadSession(incoming, "測試影片.webm", start_sec=12, expected_bytes=11)
        session.receive(b"first")
        session.receive(b"second")
        session.finish()
        self.assertEqual(session.health()["state"], "uploaded")
        self.assertEqual(session.health()["bytes_received"], 11)
        self.assertTrue(session.health()["upload_complete"])
        self.assertEqual(incoming.read_bytes(), b"firstsecond")
        session.close()
        self.assertFalse(incoming.exists())


if __name__ == "__main__":
    unittest.main()
