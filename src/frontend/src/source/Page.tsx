import { useEffect, useRef, useState } from "react";
import { ArrowClockwise, Play, Stop, VideoCamera } from "@phosphor-icons/react";
import { api } from "../api/client";
import { Badge, Card, Empty, ErrorBanner, errorText, ms } from "../components/ui";
import type { BrowserMediaHealth, BrowserUploadHealth, Status } from "../types/api";

type Scenario = { id: string; name: string; description: string };
type SourceMode = "browser_camera" | "browser_upload" | "rtsp" | "replay_scenario" | "replay_file";
type BrowserState = "idle" | "requesting" | "connecting" | "streaming" | "processing" | "error";
type MediaEventPayload = (BrowserMediaHealth | BrowserUploadHealth) & { error_code?: string };

const BROWSER_CAMERA_ID = "browser-camera";
const CAMERA_WIDTH = 854;
const CAMERA_HEIGHT = 480;
const MIME_TYPES = ["video/webm;codecs=vp8,opus", "video/webm;codecs=vp8", "video/webm"];

function mediaSocketUrl(mediaType: string, cameraId = BROWSER_CAMERA_ID, mode = ""): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const params = new URLSearchParams({ camera_id: cameraId, media_type: mediaType });
  if (mode) params.set("mode", mode);
  return `${protocol}//${window.location.host}/ws/media?${params.toString()}`;
}

function fileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function cameraError(error: unknown): string {
  const name = error instanceof DOMException ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") return "瀏覽器拒絕攝影機或麥克風權限，請在網址列允許後再試。";
  if (name === "NotFoundError") return "找不到可用的攝影機或麥克風。";
  if (name === "NotReadableError") return "攝影機或麥克風可能已被其他程式使用。";
  if (name === "OverconstrainedError") return "攝影機不支援要求的畫面設定。";
  return error instanceof Error ? error.message : "無法啟動瀏覽器攝影機。";
}

export function SourcePage({ status }: { status: Status | null }) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [mode, setMode] = useState<SourceMode>("browser_camera");
  const [target, setTarget] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadEventStart, setUploadEventStart] = useState("");
  const [uploadDuration, setUploadDuration] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState(api.sourceSnapshotUrl());
  const [browserState, setBrowserState] = useState<BrowserState>("idle");
  const [browserHealth, setBrowserHealth] = useState<BrowserMediaHealth | null>(null);
  const [sentChunks, setSentChunks] = useState(0);
  const [uploadProgress, setUploadProgress] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptRef = useRef(0);
  const intentionalCloseRef = useRef(false);
  const uploadAckBytesRef = useRef(0);

  const source = status?.source;
  const running = source?.running ?? false;
  const completed = source?.lifecycle === "completed";
  const failed = source?.lifecycle === "failed";
  const browserActive = ["requesting", "connecting", "streaming", "processing"].includes(browserState);
  const active = running || browserActive;

  useEffect(() => {
    setUploadDuration(null);
    if (!uploadFile) return;
    const url = URL.createObjectURL(uploadFile);
    const probe = document.createElement("video");
    probe.preload = "metadata";
    probe.onloadedmetadata = () => {
      if (Number.isFinite(probe.duration)) {
        setUploadDuration(probe.duration);
      }
    };
    probe.src = url;
    return () => {
      probe.removeAttribute("src");
      probe.load();
      URL.revokeObjectURL(url);
    };
  }, [uploadFile]);

  useEffect(() => {
    void api.scenarios().then((data) => setScenarios(data.scenarios)).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setSnapshot(api.sourceSnapshotUrl()), 2000);
    return () => window.clearInterval(timer);
  }, [running]);

  useEffect(() => {
    if (!browserActive) return;
    const refresh = () => {
      void api.mediaStreams().then((data) => {
        const session = data.active[0];
        if (session) setBrowserHealth(session);
      }).catch(() => undefined);
    };
    refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => window.clearInterval(timer);
  }, [browserActive]);

  const releaseBrowserResources = () => {
    if (reconnectTimerRef.current !== null) window.clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = null;
    recorderRef.current = null;
    socketRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  };

  const waitForUploadAck = (socket: WebSocket, minimumBytes: number) => new Promise<void>((resolve, reject) => {
    const deadline = Date.now() + 5_000;
    const poll = () => {
      if (uploadAckBytesRef.current >= minimumBytes) { resolve(); return; }
      if (socket.readyState !== WebSocket.OPEN) { reject(new Error("影片上傳連線已中斷")); return; }
      if (Date.now() >= deadline) { reject(new Error("後端未確認收到完整影片分片")); return; }
      window.setTimeout(poll, 50);
    };
    poll();
  });

  const waitForSocketDrain = (socket: WebSocket) => new Promise<void>((resolve, reject) => {
    const deadline = Date.now() + 120_000;
    const poll = () => {
      if (socket.readyState !== WebSocket.OPEN) { reject(new Error("影片上傳連線已中斷")); return; }
      if (socket.bufferedAmount === 0) { resolve(); return; }
      if (Date.now() >= deadline) { reject(new Error("影片上傳傳輸逾時，請重新嘗試。")); return; }
      window.setTimeout(poll, 100);
    };
    poll();
  });

  const stopBrowserCamera = () => {
    intentionalCloseRef.current = true;
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
    const socket = socketRef.current;
    if (socket && socket.readyState !== WebSocket.CLOSED) socket.close(1000, "client_stop");
    releaseBrowserResources();
    reconnectAttemptRef.current = 0;
    setBrowserState("idle");
    setBrowserHealth(null);
    setSentChunks(0);
    setUploadProgress(0);
  };

  useEffect(() => () => {
    intentionalCloseRef.current = true;
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
    if (reconnectTimerRef.current !== null) window.clearTimeout(reconnectTimerRef.current);
    socketRef.current?.close(1000, "page_unload");
    streamRef.current?.getTracks().forEach((track) => track.stop());
  }, []);

  const startBrowserCamera = async () => {
    setBusy(true); setMessage(null); setError(null); setBrowserHealth(null); setSentChunks(0); setUploadProgress(0);
    intentionalCloseRef.current = false;
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("此瀏覽器或目前連線環境不支援攝影機；請使用 HTTPS 或 localhost。");
      setBrowserState("error"); setBusy(false); return;
    }
    if (typeof MediaRecorder === "undefined") {
      setError("此瀏覽器不支援 MediaRecorder，無法傳送 WebM 串流。");
      setBrowserState("error"); setBusy(false); return;
    }
    const mediaType = MIME_TYPES.find((candidate) => MediaRecorder.isTypeSupported(candidate));
    if (!mediaType) {
      setError("此瀏覽器沒有可用的 WebM 編碼格式。");
      setBrowserState("error"); setBusy(false); return;
    }
    try {
      setBrowserState("requesting");
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: CAMERA_WIDTH, max: CAMERA_WIDTH }, height: { ideal: CAMERA_HEIGHT, max: CAMERA_HEIGHT }, frameRate: { ideal: 15, max: 30 } },
        audio: true,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
      const connectSocket = () => {
        if (intentionalCloseRef.current || streamRef.current !== stream) return;
        setBrowserState("connecting");
        const socket = new WebSocket(mediaSocketUrl(mediaType));
        socket.binaryType = "arraybuffer";
        socketRef.current = socket;
        socket.onopen = () => {
          if (intentionalCloseRef.current) { socket.close(1000, "client_stop"); return; }
          reconnectAttemptRef.current = 0;
          setError(null);
          try {
            // Restart the recorder for every new WebSocket session. A fresh
            // WebM header lets the backend decode cleanly after reconnect.
            const oldRecorder = recorderRef.current;
            if (oldRecorder && oldRecorder.state !== "inactive") oldRecorder.stop();
            const recorder = new MediaRecorder(stream, { mimeType: mediaType, videoBitsPerSecond: 1_500_000 });
            recorderRef.current = recorder;
            recorder.ondataavailable = (event) => {
              if (event.data.size === 0 || socket.readyState !== WebSocket.OPEN) return;
              socket.send(event.data);
              setSentChunks((current) => current + 1);
            };
            recorder.onerror = () => setError("瀏覽器錄影器發生錯誤，串流會嘗試重新連線。");
            recorder.start(1000);
            setBrowserState("streaming");
            setMessage("瀏覽器攝影機已啟動，正在持續傳送影像與音訊供分析。");
          } catch (exc) {
            setError(cameraError(exc));
            intentionalCloseRef.current = true;
            socket.close();
            releaseBrowserResources();
            setBrowserState("error");
          } finally { setBusy(false); }
        };
        socket.onmessage = (event) => {
          if (typeof event.data !== "string") return;
          try {
            const payload = JSON.parse(event.data) as { type?: string; payload?: MediaEventPayload };
            if ((payload.type === "media.stream.ready" || payload.type === "media.stream.progress") && payload.payload && "camera_id" in payload.payload) setBrowserHealth(payload.payload);
            if (payload.type === "media.stream.failed") {
              setError(`後端無法接收瀏覽器串流（${payload.payload?.error_code ?? "unknown"}）。`);
              intentionalCloseRef.current = true;
              socket.close();
              releaseBrowserResources();
              setBrowserState("error");
            }
          } catch { setError("收到無法辨識的串流狀態。"); }
        };
        socket.onerror = () => {
          if (!intentionalCloseRef.current) setError("瀏覽器串流連線中斷，正在自動重連…");
          socket.close();
        };
        socket.onclose = () => {
          if (intentionalCloseRef.current || socketRef.current !== socket) return;
          socketRef.current = null;
          const recorder = recorderRef.current;
          if (recorder && recorder.state !== "inactive") recorder.stop();
          recorderRef.current = null;
          setBrowserState("connecting");
          setBusy(false);
          const delay = Math.min(10_000, 500 * 2 ** reconnectAttemptRef.current);
          reconnectAttemptRef.current += 1;
          reconnectTimerRef.current = window.setTimeout(() => {
            reconnectTimerRef.current = null;
            connectSocket();
          }, delay);
        };
      };
      connectSocket();
    } catch (exc) {
      releaseBrowserResources(); setBrowserState("error"); setError(cameraError(exc)); setBusy(false);
    }
  };

  const startBrowserUpload = async () => {
    const file = uploadFile;
    if (!file) { setError("請先選擇要上傳的影片。"); return; }
    if (!file.type.startsWith("video/")) { setError("請選擇影片檔案。"); return; }
    const eventStartMs = Date.parse(uploadEventStart);
    if (!Number.isFinite(eventStartMs) || eventStartMs <= 0) { setError("請設定影片第一幀在歷史上的日期與時間。"); return; }
    setBusy(true); setMessage(null); setError(null); setBrowserHealth(null); setSentChunks(0); setUploadProgress(0);
    intentionalCloseRef.current = false;
    reconnectAttemptRef.current = 0;
    uploadAckBytesRef.current = 0;
    setBrowserState("connecting");
    const mediaType = file.type || "video/webm";
    const socket = new WebSocket(`${mediaSocketUrl(mediaType, "browser-upload", "demo_upload")}&filename=${encodeURIComponent(file.name)}&file_size=${file.size}&event_start_ms=${eventStartMs}`);
    socket.binaryType = "arraybuffer";
    socketRef.current = socket;
    socket.onopen = async () => {
      try {
        const chunkSize = 512 * 1024;
        for (let offset = 0; offset < file.size; offset += chunkSize) {
          if (intentionalCloseRef.current || socket.readyState !== WebSocket.OPEN) throw new Error("影片上傳連線已中斷");
          while (socket.bufferedAmount > chunkSize * 2) {
            await new Promise<void>((resolve) => window.setTimeout(resolve, 50));
            if (intentionalCloseRef.current || socket.readyState !== WebSocket.OPEN) throw new Error("影片上傳連線已中斷");
          }
          const end = Math.min(offset + chunkSize, file.size);
          socket.send(await file.slice(offset, end).arrayBuffer());
          setSentChunks((current) => current + 1);
          setUploadProgress(Math.round((end / file.size) * 100));
          try {
            await waitForUploadAck(socket, end);
          } catch (exc) {
            if (socket.readyState !== WebSocket.OPEN) throw exc;
            setMessage("正在等待影片分片傳輸完成…");
            await waitForSocketDrain(socket);
          }
        }
        setBrowserState("streaming");
        setMessage("影片已上傳，後端正在壓成 480p，完成後會依影片內時長慢速送入相同分析管線…");
        socket.send(JSON.stringify({ type: "media.upload.complete" }));
      } catch (exc) {
        if (!intentionalCloseRef.current) {
          setError(cameraError(exc)); setBrowserState("error");
        }
        socket.close(); setBusy(false);
      }
    };
    socket.onmessage = (event) => {
      if (typeof event.data !== "string") return;
      try {
        const payload = JSON.parse(event.data) as { type?: string; payload?: MediaEventPayload };
        if (payload.type === "media.stream.ack" && payload.payload && "bytes_received" in payload.payload) {
          uploadAckBytesRef.current = Math.max(uploadAckBytesRef.current, payload.payload.bytes_received);
        }
        if (payload.type === "media.stream.processing") {
          setBrowserState("processing");
          setMessage("影片正在壓成 480p，完成後會依影片內時長排隊分析；不會瞬間灌入請求。 ");
        }
        if ((payload.type === "media.stream.ready" || payload.type === "media.stream.progress") && payload.payload && "camera_id" in payload.payload) setBrowserHealth(payload.payload);
        if (payload.type === "media.stream.completed") {
          intentionalCloseRef.current = true;
          setBrowserState("idle"); setMessage("影片已按影片時間完整模擬，結果已寫入相同的即時分析紀錄。"); setBusy(false);
          releaseBrowserResources();
        }
        if (payload.type === "media.stream.failed") {
          setError(`後端無法處理影片（${payload.payload?.error_code ?? payload.payload?.error ?? "unknown"}）。`);
          intentionalCloseRef.current = true; socket.close(); releaseBrowserResources(); setBrowserState("error"); setBusy(false);
        }
      } catch { setError("收到無法辨識的影片處理狀態。"); }
    };
    socket.onerror = () => {
      if (!intentionalCloseRef.current) { setError("影片上傳連線中斷。"); setBrowserState("error"); setBusy(false); }
    };
    socket.onclose = () => {
      if (!intentionalCloseRef.current) {
        releaseBrowserResources(); setBrowserState("error"); setBusy(false);
        setError((current) => current ?? "影片上傳連線已中斷。");
      }
    };
  };

  const selectMode = (next: SourceMode) => {
    if (next !== "browser_camera" && browserActive) stopBrowserCamera();
    setMode(next); setTarget(""); setMessage(null); setError(null);
    if (next !== "browser_upload") setUploadFile(null);
  };

  const start = async (kind: string, value: string) => {
    setBusy(true); setMessage(null); setError(null);
    if (!value) { setError("請先選擇或輸入來源，再啟動分析。"); setBusy(false); return; }
    try { await api.startSource(kind, value); setMessage("影像來源已啟動，分析管線正在接收畫面。"); }
    catch (exc) { setError(errorText(exc)); }
    finally { setBusy(false); }
  };

  const stop = async () => {
    if (browserActive) { stopBrowserCamera(); setMessage("瀏覽器攝影機已停止。"); return; }
    setBusy(true); setMessage(null); setError(null);
    try { await api.stopSource(); setMessage("影像來源已停止。"); }
    catch (exc) { setError(errorText(exc)); }
    finally { setBusy(false); }
  };

  const statusLabel = browserState === "streaming" ? "串流中" : browserState === "processing" ? "壓縮與排隊分析中" : browserState === "requesting" ? "等待權限" : browserState === "connecting" ? "連線中" : browserState === "error" ? "串流錯誤" : completed ? "錄影播放完成" : failed ? "來源失敗" : active ? "分析中" : "未啟動";
  const statusTone = browserState === "error" || failed ? "bad" : active ? "ok" : "muted";

  return (
    <div className="page-stack">
      <header className="page-heading">
        <div><span className="eyebrow">影像來源</span><h1>即時影像</h1><p>瀏覽器攝影機、RTSP、模擬情境與本機錄影共用同一條分析管線。</p></div>
        <Badge tone={statusTone} dot>{statusLabel}</Badge>
      </header>
      <div className="source-layout">
        <Card className="preview-card">
          <div className="preview-frame">
            {mode === "browser_camera" && browserActive ? <video ref={videoRef} autoPlay muted playsInline aria-label="瀏覽器攝影機即時畫面" /> : mode === "browser_upload" && browserActive ? <div className="preview-empty"><VideoCamera size={38} /><b>影片上傳中</b><span>{uploadProgress}% · 後端正在解碼並分析</span></div> : running || completed ? <img src={snapshot} alt={completed ? "錄影最後一個分析影格" : "最新分析影格"} /> : (
              <div className="preview-empty"><VideoCamera size={38} /><b>尚未接收影像</b><span>啟動來源後顯示最新取樣影格</span></div>
            )}
            <div className="preview-label"><i className={`status-dot ${failed ? "bad" : active ? "ok" : "muted"}`} />{mode === "browser_camera" && browserActive ? "瀏覽器即時畫面" : mode === "browser_upload" && browserActive ? "上傳影片處理中" : completed ? "錄影播放完成 · 最後影格" : "分析用低頻預覽"}</div>
          </div>
          <div className="source-metrics">
            {browserActive || browserHealth ? <>
              <span><b>{sentChunks}</b>已送出片段</span><span><b>{browserHealth?.frames_emitted ?? 0}</b>後端影格</span>
              <span><b>{browserHealth?.audio_bytes ? `${Math.round(browserHealth.audio_bytes / 1024)} KB` : "—"}</b>音訊</span><span><b>{browserHealth?.error ?? "正常"}</b>串流狀態</span>
            </> : <>
              <span><b>{source?.kind ?? "—"}</b>來源</span><span><b>{source?.frames_emitted ?? 0}</b>已接收影格</span>
              <span><b>{source?.last_frame_age_ms == null ? "—" : ms(source.last_frame_age_ms)}</b>最後影格</span><span><b>{source?.reconnects ?? 0}</b>重新連線</span>
            </>}
          </div>
          {source?.error && <p className="banner bad">來源錯誤：{source.error}</p>}
        </Card>
        <Card title="選擇來源" className="source-control-card">
          <div className="segmented" role="tablist" aria-label="來源類型">
            <button aria-selected={mode === "browser_camera"} onClick={() => selectMode("browser_camera")}>瀏覽器攝影機</button>
            <button aria-selected={mode === "browser_upload"} onClick={() => selectMode("browser_upload")}>上傳影片</button>
            <button aria-selected={mode === "rtsp"} onClick={() => selectMode("rtsp")}>RTSP 鏡頭</button>
            <button aria-selected={mode === "replay_scenario"} onClick={() => selectMode("replay_scenario")}>模擬情境</button>
            <button aria-selected={mode === "replay_file"} onClick={() => selectMode("replay_file")}>本機錄影</button>
          </div>
          {mode === "browser_camera" && <div className="camera-help"><b>從目前瀏覽器分享攝影機（480p）</b><span>影像與麥克風會以每秒一段的 WebM 傳到本機後端；影像會限制在 854×480 以控制 L2 視覺 token。</span><small>請使用 HTTPS 或 localhost，第一次啟動時瀏覽器會詢問攝影機與麥克風權限。</small></div>}
          {mode === "browser_upload" && <div className="camera-help"><b>上傳歷史影片並依影片時間慢速分析</b><span>影片會先在本機後端保存並壓成 480p，再以影片內的時間節奏送入與瀏覽器攝影機相同的 FrameWindow、L1、L2、L3 與 Policy 流程；不會把所有影格瞬間灌入 queue。</span><small>請設定影片第一幀在歷史上的日期與時間；影片內第 N 秒的事件會記錄在這個時間加 N 秒。</small></div>}
          {mode === "browser_upload" && <label className="field"><span>選擇影片</span><input type="file" accept="video/*" onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)} />{uploadFile && <small className="file-selection">{uploadFile.name} · {fileSize(uploadFile.size)}{uploadDuration !== null ? ` · 長度 ${Math.floor(uploadDuration / 60)}:${String(Math.floor(uploadDuration % 60)).padStart(2, "0")}` : ""}</small>}</label>}
          {mode === "browser_upload" && <label className="field"><span>影片第一幀的歷史日期／時間</span><input type="datetime-local" value={uploadEventStart} onChange={(event) => setUploadEventStart(event.target.value)} required /><small className="file-selection">影片內第 0 秒從這個時間開始；之後每個事件依影片時間軸記錄，不使用目前系統時間。</small></label>}
          {mode === "rtsp" && <label className="field"><span>RTSP 位址</span><input type="password" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="rtsp://攝影機位址（不會回傳至瀏覽器）" /></label>}
          {mode === "replay_file" && <label className="field"><span>主機上的影片路徑</span><input value={target} onChange={(e) => setTarget(e.target.value)} placeholder="C:\\care-data\\sample.mp4" /></label>}
          {mode === "replay_scenario" && <div className="scenario-list">{scenarios.length === 0 ? <Empty>沒有可用的模擬情境。</Empty> : scenarios.map((scenario) => <button key={scenario.id} onClick={() => setTarget(scenario.id)} aria-pressed={target === scenario.id}><b>{scenario.name}</b><span>{scenario.description || "驗證完整 Cascade 行為"}</span></button>)}</div>}
          <div className="button-row">
            {mode === "browser_camera" ? <button className="action primary" disabled={busy || browserActive} onClick={() => void startBrowserCamera()}><VideoCamera size={17} weight="fill" />啟動瀏覽器攝影機</button> : mode === "browser_upload" ? <button className="action primary" disabled={busy || browserActive || !uploadFile} onClick={() => void startBrowserUpload()}><Play size={17} weight="fill" />上傳、壓成 480p 並分析</button> : <button className="action primary" disabled={busy || !target} onClick={() => void start(mode, target)}><Play size={17} weight="fill" />開始分析</button>}
            <button className="action" disabled={busy || !active} onClick={() => void stop()}><Stop size={17} weight="fill" />停止</button>
            <button className="action ghost" disabled={busy || browserActive || !running || !target} title={running && !target ? "重新連線需要先在上方指定來源" : undefined} onClick={() => void start(mode, target)}><ArrowClockwise size={17} />重新連線</button>
          </div>
          {error && <ErrorBanner>{error}</ErrorBanner>}
          {message && <p className="banner">{message}</p>}
          <p className="privacy-note">瀏覽器攝影機只在你按下啟動後傳送；上傳影片只會傳到此 v5 後端。停止後會關閉媒體連線。</p>
        </Card>
      </div>
    </div>
  );
}
