import { useRef, useState } from "react";
import { Card } from "../components/ui";

type CaptureStats = { bytes_received?: number; chunks_received?: number; frames_emitted?: number; audio_bytes?: number; error?: string | null };

function mediaUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/media?camera_id=browser-camera&media_type=video/webm`;
}

export function CapturePanel() {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<CaptureStats | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const socket = useRef<WebSocket | null>(null);

  const stop = () => {
    recorder.current?.stop();
    recorder.current = null;
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    if (socket.current && socket.current.readyState < WebSocket.CLOSING) socket.current.close();
    socket.current = null;
    setRunning(false);
  };

  const start = async () => {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("此瀏覽器不支援攝影機／麥克風錄製。請使用新版瀏覽器。 ");
      return;
    }
    try {
      const nextStream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 15, max: 30 } },
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      const nextSocket = new WebSocket(mediaUrl());
      nextSocket.binaryType = "arraybuffer";
      nextSocket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as { type?: string; payload?: CaptureStats };
          if (message.payload) setStats(message.payload);
          if (message.type === "media.stream.failed") setError("media stream failed");
        } catch { /* progress is best effort */ }
      };
      nextSocket.onerror = () => setError("無法連接 v5 media pipeline。 ");
      nextSocket.onopen = () => {
        const mimeType = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"]
          .find((candidate) => MediaRecorder.isTypeSupported(candidate)) || "";
        const nextRecorder = new MediaRecorder(nextStream, mimeType ? { mimeType } : undefined);
        nextRecorder.ondataavailable = (event) => {
          if (event.data.size && nextSocket.readyState === WebSocket.OPEN) nextSocket.send(event.data);
        };
        nextRecorder.onerror = () => setError("瀏覽器錄製失敗。 ");
        nextRecorder.start(1000);
        recorder.current = nextRecorder;
        stream.current = nextStream;
        socket.current = nextSocket;
        setRunning(true);
      };
      nextSocket.onclose = () => {
        nextStream.getTracks().forEach((track) => track.stop());
        setRunning(false);
      };
    } catch (exc) {
      nextStreamStop(stream);
      setError((exc as Error).message || "無法取得攝影機／麥克風權限。 ");
    }
  };

  return (
    <Card title="Browser media pipeline" aside={running ? "live" : "idle"}>
      <div className="row" style={{ marginBottom: ".6rem" }}>
        <button className="action primary" onClick={() => void start()} disabled={running}>Start camera + microphone</button>
        <button className="action" onClick={stop} disabled={!running}>Stop</button>
      </div>
      <p className="muted" style={{ margin: 0 }}>
        Continuous WebM → ffmpeg → 2 FPS frames + audio → L0 change gate → local vLLM.
      </p>
      {stats && <p className="muted mono" style={{ margin: ".45rem 0 0" }}>
        {stats.chunks_received || 0} chunks · {stats.frames_emitted || 0} frames · {stats.audio_bytes || 0} audio bytes
      </p>}
      {error && <p className="banner bad" style={{ margin: ".6rem 0 0" }}>{error}</p>}
    </Card>
  );
}

function nextStreamStop(ref: { current: MediaStream | null }) {
  ref.current?.getTracks().forEach((track) => track.stop());
  ref.current = null;
}
