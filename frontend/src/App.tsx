import { useCallback, useEffect, useRef, useState } from "react";
import { api, formatDate, mediaWsUrl, wsUrl, type Json } from "./api";

const eventNames: Record<string, string> = {
  fall: "跌倒", hydration: "喝水", person_present: "人物在場", person_walking: "人物行走",
  person_sitting: "人物坐姿", person_lying: "人物躺姿", person_entered: "人物進入", person_left: "人物離開",
  person_inactive: "人物不動", person_stood_up: "人物起身", person_sat_down: "人物坐下", person_lay_down: "人物躺下", person_got_up: "人物起來",
  doorbell: "門鈴", door_knock: "敲門", door_open: "門開", door_closed: "門關", fridge_open: "冰箱開",
  fridge_closed: "冰箱關", water_running: "流水聲", toilet_flush: "沖水聲", washing_machine: "洗衣機",
  microwave: "微波爐", rice_cooker: "電鍋", range_hood: "抽油煙機", dishes: "碗盤聲", impact_sound: "撞擊聲",
  cough: "咳嗽", tv_audio: "電視聲", speech_activity: "說話活動", alarm_sound: "警報聲", object_cup: "杯子",
  object_bottle: "瓶子", object_phone: "手機", object_remote: "遙控器", object_bag: "包包", object_pet: "寵物",
  object_vehicle: "車輛", smoke: "煙霧", fire: "火焰",
};

const serviceNames: Record<string, string> = {
  camera: "攝影機", microphone: "麥克風", virtual_camera: "虛擬串流", local_vlm: "流程多模態模型",
  main_agent: "主 Agent", database: "SQLite", frigate_api: "Frigate",
};

function eventLabel(type?: string) { return type ? (eventNames[type] || type) : "事件"; }
function formatOffset(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return "—";
  const total = Math.max(0, Math.round(Number(value) / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}
function number(value: unknown, fallback = "—") { return value === undefined || value === null || value === "" ? fallback : String(value); }
function statusClass(value?: string | boolean) { return typeof value === "boolean" ? (value ? "healthy" : "blocked") : value || "unknown"; }
function postureLabel(value?: string) { return ({ standing: "站立", sitting: "坐著", lying: "躺著", unknown: "未知" } as Record<string, string>)[value || "unknown"] || value || "未知"; }
function toneForEvent(type?: string) { return type?.includes("fall") || type === "fire" || type === "smoke" || type === "alarm_sound" ? "urgent" : type?.includes("stood") || type?.includes("sat") ? "accent" : "neutral"; }
function serviceSummary(item?: Json) {
  const detail = item?.detail;
  if (typeof detail === "string") return detail;
  if (!detail || typeof detail !== "object") return "—";
  if (detail.model) return String(detail.model);
  if (detail.mode) return `mode ${detail.mode}`;
  if (detail.path) return "WAL database";
  if (detail.browser_capture) return "browser capture";
  if (detail.configured === false) return "not configured";
  return "available";
}

function Badge({ status }: { status?: string | boolean }) {
  const text = typeof status === "boolean" ? (status ? "通過" : "阻擋") : (status || "unknown");
  return <span className={`badge ${statusClass(status)}`}>{text}</span>;
}

function Panel({ title, eyebrow, children, className = "" }: { title: string; eyebrow?: string; children: any; className?: string }) {
  return <section className={`panel ${className}`}><div className="panel-heading"><div>{eyebrow && <div className="panel-eyebrow">{eyebrow}</div>}<h2>{title}</h2></div></div>{children}</section>;
}

function Metric({ label, value, hint, accent = "" }: { label: string; value: string | number; hint?: string; accent?: string }) {
  return <div className={`metric ${accent}`}><span>{label}</span><strong>{value}</strong>{hint && <small>{hint}</small>}</div>;
}

function mergeById(previous: Json[], item: Json, limit = 80) {
  return [item, ...previous.filter(existing => existing.id !== item.id)].slice(0, limit);
}

function CapturePanel({ onUpdated, onStream }: { onUpdated: () => void; onStream: (value: Json | null) => void }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastVadRef = useRef<boolean | null>(null);
  const [active, setActive] = useState(false);
  const [micLevel, setMicLevel] = useState(0);
  const [streamStats, setStreamStats] = useState<Json | null>(null);
  const [error, setError] = useState("");

  async function updateStatus(cameraActive: boolean, microphoneActive: boolean) {
    await api("/api/capture/status", { method: "POST", body: JSON.stringify({ camera_active: cameraActive, microphone_active: microphoneActive }) });
  }

  async function startCapture() {
    setError("");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("此瀏覽器不支援 MediaStream/MediaRecorder，請使用 HTTPS 的新版瀏覽器。");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      streamRef.current = stream;
      if (videoRef.current) { videoRef.current.srcObject = stream; await videoRef.current.play(); }
      const audioContext = new AudioContext();
      const analyser = audioContext.createAnalyser(); analyser.fftSize = 512;
      audioContext.createMediaStreamSource(stream).connect(analyser); audioContextRef.current = audioContext;
      const samples = new Uint8Array(analyser.frequencyBinCount);
      const meter = () => {
        analyser.getByteTimeDomainData(samples);
        let sum = 0; for (const value of samples) { const normalized = (value - 128) / 128; sum += normalized * normalized; }
        const level = Math.min(1, Math.sqrt(sum / samples.length) * 4); setMicLevel(level);
        const speaking = level > 0.08;
        if (lastVadRef.current !== speaking) {
          lastVadRef.current = speaking;
          void api("/api/audio/vad", { method: "POST", body: JSON.stringify({ segment_id: `browser-${Date.now()}`, active: speaking, probability: Math.min(.99, level + .5) }) });
        }
        rafRef.current = requestAnimationFrame(meter);
      };
      meter();
      const mimeType = ["video/webm;codecs=vp8,opus", "video/webm", "video/mp4"].find(candidate => MediaRecorder.isTypeSupported(candidate)) || "video/webm";
      const socket = new WebSocket(mediaWsUrl("browser-camera", mimeType)); socketRef.current = socket;
      socket.onmessage = message => {
        try {
          const payload = JSON.parse(message.data);
          if (payload.type === "media.stream.ready" || payload.type === "media.stream.progress") { setStreamStats(payload.payload); onStream(payload.payload); }
        } catch { /* keep the camera stream alive if a progress packet is malformed */ }
      };
      socket.onerror = () => setError("無法連到 backend virtual-camera stream。");
      socket.onopen = () => {
        const recorder = new MediaRecorder(stream, { mimeType }); recorderRef.current = recorder;
        recorder.ondataavailable = event => { if (event.data.size && socket.readyState === WebSocket.OPEN) socket.send(event.data); };
        recorder.start(500); setActive(true); void updateStatus(true, true); onUpdated();
      };
      socket.onclose = () => { setActive(false); onStream(null); };
    } catch (cause) {
      streamRef.current?.getTracks().forEach(track => track.stop()); streamRef.current = null;
      setError(cause instanceof Error ? cause.message : "無法取得攝影機／麥克風權限");
    }
  }

  function stopCapture() {
    if (recorderRef.current && recorderRef.current.state !== "inactive") recorderRef.current.stop(); recorderRef.current = null;
    streamRef.current?.getTracks().forEach(track => track.stop()); streamRef.current = null;
    if (socketRef.current && socketRef.current.readyState < WebSocket.CLOSING) socketRef.current.close(); socketRef.current = null;
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current); rafRef.current = null;
    void audioContextRef.current?.close(); audioContextRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setActive(false); setMicLevel(0); setStreamStats(null); onStream(null); lastVadRef.current = null;
    void updateStatus(false, false); onUpdated();
  }

  useEffect(() => () => {
    recorderRef.current?.stop(); streamRef.current?.getTracks().forEach(track => track.stop());
    if (socketRef.current && socketRef.current.readyState < WebSocket.CLOSING) socketRef.current.close();
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current); void audioContextRef.current?.close();
  }, []);

  return <Panel title="攝影機與麥克風" eyebrow="LIVE INPUT" className="capture-panel">
    <div className="capture-grid"><div className="camera-view"><video ref={videoRef} muted playsInline /><div className="camera-placeholder">{active ? "CAMERA STREAM" : "CAMERA OFF"}</div><div className="camera-status"><Badge status={active ? "healthy" : "unavailable"} /> {active ? "正在傳送連續影像" : "等待權限"}</div></div>
      <div className="capture-side"><div className="button-row"><button className="primary" onClick={() => void startCapture()} disabled={active}>開啟攝影機＋麥克風</button><button onClick={stopCapture} disabled={!active}>停止</button></div>
        <div className="input-meter"><div><span>麥克風音量</span><strong>{Math.round(micLevel * 100)}%</strong></div><div className="meter-track"><i style={{ width: `${Math.round(micLevel * 100)}%` }} /></div></div>
        <div className="capture-facts"><div><span>輸入方式</span><strong>MediaStream → WebSocket</strong></div><div><span>快速 Gate</span><strong>每 5 秒檢查影像／音訊變化</strong></div><div><span>第二層觀察</span><strong>10 frames + optional audio</strong></div>{streamStats && <div><span>目前串流</span><strong>{streamStats.gate_windows || 0} gate · {streamStats.observation_windows || streamStats.vlm_windows || 0} 觀察 · {streamStats.analysis_pending || 0} 排隊</strong></div>}</div>
        {error && <p className="error-text">{error}</p>}
      </div></div>
    <p className="caption">畫面不是截圖；瀏覽器提供的是連續虛擬攝影機串流。原始媒體只保留目前設定的短時間滾動窗口。</p>
  </Panel>;
}

function CurrentStatePanel({ observation, tracker, scene, stream }: { observation: Json | null; tracker: Json | null; scene: Json | null; stream: Json | null }) {
  const stable = tracker?.state?.stable_posture || observation?.posture || "unknown";
  const candidate = tracker?.state?.candidate_posture;
  const audioUnavailable = Boolean(observation?.audio_uncertainty_reasons?.includes?.("audio_not_available_to_active_model"));
  return <Panel title="目前狀態" eyebrow="STATE, NOT A SINGLE FRAME" className="state-panel">
    <div className="state-hero"><div className={`posture-icon ${stable}`}><span>{stable === "standing" ? "↑" : stable === "sitting" ? "⌄" : stable === "lying" ? "—" : "?"}</span></div><div><div className="state-label">人物姿態</div><h3>{postureLabel(stable)}</h3><p>{candidate ? `正在確認：${postureLabel(candidate)}（${tracker?.state?.candidate_count || 1}/2）` : "已通過目前時間序列穩定條件"}</p></div><Badge status={observation ? "healthy" : "waiting"} /></div>
    <div className="metric-grid"><Metric label="人物可見" value={observation ? (observation.person_visible ? "是" : "否") : "—"} hint="目前窗口" /><Metric label="觀察信心" value={observation ? Number(observation.confidence || 0).toFixed(2) : "—"} hint="VLM" /><Metric label="最新窗口" value={formatOffset(observation?.observed_at_offset_ms)} hint="串流時間" accent="accent" /><Metric label="第二層視窗" value={number(stream?.observation_windows || stream?.vlm_windows, "0")} hint={`${number(stream?.vlm_frames, "0")} frames`} /></div>
    {scene && <div className="scene-note"><span>場景註腳</span><strong>{scene.location || "未知位置"}</strong><p>{scene.scene_description || "—"}</p><small>{scene.objects?.join(" · ") || "沒有非人物物體資料"}</small></div>}
    {observation && <div className="observation-facts"><div><span>垂直轉換</span><strong>{observation.vertical_transition || "none"}</strong></div><div><span>聲音</span><strong>{audioUnavailable ? "音訊不可用" : (observation.audio_events?.join("、") || "無顯著聲音")}</strong></div><div><span>變化短述</span><strong>{observation.change_summary || "無"}</strong></div><div><span>語音文字</span><strong>{audioUnavailable ? "音訊不可用" : (observation.speech_transcript || "無")}</strong></div></div>}
  </Panel>;
}

function TimelinePanel({ events }: { events: Json[] }) {
  return <Panel title="事件時間軸" eyebrow="CONFIRMED TRANSITIONS" className="timeline-panel"><div className="timeline-intro">只把已跨窗口確認的事件放在這裡；VLM 瞬時觀察會留在證據區，不會冒充事件。</div><div className="event-list">{events.length ? events.slice(0, 40).map(event => {
    const attrs = event.attributes_json || event.attributes || {};
    const offset = attrs.occurred_offset_ms ?? event.source_offset_ms;
    return <article className={`event-row ${toneForEvent(event.event_type)}`} key={event.id}><div className="event-dot" /><div className="event-main"><div className="event-title"><strong>{eventLabel(event.event_type)}</strong><Badge status={event.status} /><span>{event.source === "recognition" ? "時間狀態追蹤" : "canonical"}</span></div><p>{attrs.from_state && attrs.to_state ? `${postureLabel(attrs.from_state)} → ${postureLabel(attrs.to_state)}` : (attrs.reason || "已保存事件")}</p><div className="event-meta"><b>{formatDate(event.occurred_at)}</b><span>串流 {formatOffset(offset)}</span>{attrs.confirmed_offset_ms !== undefined && <span>確認 {formatOffset(attrs.confirmed_offset_ms)}</span>}<span>信心 {Number(event.confidence || 0).toFixed(2)}</span></div></div><code>{event.id.slice(-8)}</code></article>;
  }) : <div className="empty">尚無已確認事件。穩定狀態會先建立基線，跨窗口確認後才會出現在這裡。</div>}</div></Panel>;
}

function AgentPanel({ runs, trace }: { runs: Json[]; trace: Json[] }) {
  const latest = runs[0]; const judgment = latest?.analysis_json || latest?.judgment; const policy = latest?.policy_json || latest?.policy;
  const list = (items: string[] | undefined, empty: string) => items?.length ? <ul>{items.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul> : <p className="muted">{empty}</p>;
  return <Panel title="主 Agent 判斷" eyebrow="AUDITABLE OUTPUT · OMNI" className="agent-panel">
    {latest ? <><div className="agent-current-head"><div><Badge status={latest.status} /><strong>{policy?.final_action || latest.decision || "insufficient_data"}</strong><span>{formatDate(latest.created_at || latest.started_at)}</span></div><small>{latest.window_id || latest.trigger_id}</small></div>{judgment ? <><div className="agent-summary"><span>這一輪 Agent 的結論</span><p>{judgment.situation_summary || "—"}</p></div><div className="metric-grid agent-metrics"><Metric label="階段" value={judgment.situation_phase || "—"} /><Metric label="風險" value={policy?.risk_level || judgment.risk_level || "unknown"} /><Metric label="注意程度" value={policy?.attention_level || judgment.attention_level || "none"} /><Metric label="信心" value={Number(judgment.confidence || 0).toFixed(2)} /></div><div className="analysis-grid"><div className="analysis-block"><h3>Agent 看到的事實</h3>{list(judgment.observed_facts, "沒有列出直接事實")}</div><div className="analysis-block"><h3>跨窗口時序判斷</h3><p>{judgment.temporal_assessment || "—"}</p></div><div className="analysis-block wide"><h3>事件判斷</h3>{judgment.event_assessments?.length ? <div className="assessment-grid">{judgment.event_assessments.map((item: Json, index: number) => <div className="assessment" key={`${index}-${item.event_type}`}><strong>{eventLabel(item.event_type)}</strong><Badge status={item.assessment} /><p>{item.reason}</p><small>信心 {Number(item.confidence || 0).toFixed(2)} · frames {item.evidence_frame_indexes?.join(", ") || "—"}</small></div>)}</div> : <p className="muted">本輪沒有額外事件判斷</p>}</div><div className="analysis-block"><h3>Unknown</h3>{list(judgment.unknowns, "沒有列出未知事項")}</div><div className="analysis-block"><h3>下一步</h3><p>{judgment.next_action || "—"}</p>{judgment.ask_question && <div className="question">詢問：{judgment.ask_question}</div>}</div></div><div className="policy-row"><div><h3>程式裁決</h3>{Object.entries(policy?.gates || {}).map(([key, value]) => <span key={key}><Badge status={Boolean(value)} /> {key}</span>)}</div><div><h3>理由</h3><p>{policy?.reasons?.slice(0, 3).join("；") || judgment.decision_reasons?.slice(0, 3).join("；") || "—"}</p></div></div></> : <div className="empty">主 Agent 正在分析；失敗時會 fail closed 為 silent。</div>}</> : <div className="empty">等待第一輪主 Agent 判斷。</div>}
    <div className="rounds"><div className="subheading"><span>所有分析輪次</span><small>{runs.length} rounds · 持久資料</small></div>{runs.slice(0, 12).map((run, index) => { const item = run.analysis_json || {}; const runPolicy = run.policy_json || {}; return <article className={`round-row ${index === 0 ? "current" : ""}`} key={run.id}><div className="round-index">{String(index + 1).padStart(2, "0")}</div><div><div className="round-title"><strong>{runPolicy.final_action || run.decision}</strong><Badge status={run.status} /><span>{formatDate(run.created_at)}</span></div><p>{item.situation_summary || run.error_code || "尚未有 structured judgment"}</p></div><small>{run.window_id || run.trigger_id}</small></article>; })}</div>
    <div className="trace"><div className="subheading"><span>每輪即時分析／行動 trace</span><small>不會因新訊息消失</small></div>{trace.slice(0, 24).map(item => <div className="trace-row" key={item.id}><Badge status={item.stage} /><span>{item.message}</span><small>{formatDate(item.occurred_at)}</small></div>)}</div>
    <p className="caption">前端顯示的是模型可稽核摘要、證據索引與 deterministic policy；不顯示隱藏 chain-of-thought token。</p>
  </Panel>;
}

function EvidencePanel({ observation, descriptions, transcripts, changeGates, liveFeed }: { observation: Json | null; descriptions: Json[]; transcripts: Json[]; changeGates: Json[]; liveFeed: Json[] }) {
  return <Panel title="證據與語音" eyebrow="OBSERVATIONS ARE NOT EVENTS" className="evidence-panel"><div className="evidence-grid"><div><h3>快速變化 Gate</h3>{changeGates.length ? changeGates.slice(0, 4).map(item => <div className="evidence-card" key={item.id}><div className="evidence-title"><Badge status={item.changed ? "accent" : "none"} /><strong>{item.changed ? "有變化" : "無變化"}</strong><span>{formatOffset(item.end_offset_ms)}</span></div><p>{item.change_summary || "—"}</p><small>{formatOffset(item.start_offset_ms)}–{formatOffset(item.end_offset_ms)} · score {item.change_score === null ? "—" : Number(item.change_score || 0).toFixed(3)}</small></div>) : <div className="empty">等待快速變化 Gate…</div>}</div><div><h3>最近 VLM 觀察</h3>{observation ? <div className="evidence-card"><div className="evidence-title"><Badge status={observation.change_detected ? "accent" : "healthy"} /><strong>{postureLabel(observation.posture)}</strong><span>{formatOffset(observation.observed_at_offset_ms)}</span></div><p>人物{observation.person_visible ? "可見" : "不可見"}；{observation.vertical_transition !== "none" ? `垂直轉換 ${observation.vertical_transition}；` : "沒有垂直轉換；"}警示 {observation.warning_signal || "none"}。</p><small>{observation.change_summary || "沒有語意變化短述"}{observation.speech_transcript ? ` · 「${observation.speech_transcript}」` : ""}</small></div> : <div className="empty">只有 Gate 判定有變化時才呼叫第二層 VLM。</div>}</div><div><h3>已保存描述</h3>{descriptions.length ? descriptions.slice(0, 4).map(item => <div className="evidence-card" key={item.id}><div className="evidence-title"><Badge status={item.warning_level || "none"} /><strong>{formatOffset(item.start_offset_ms)}–{formatOffset(item.end_offset_ms)}</strong></div><p>{item.description_text}</p><small>{item.changes?.join(" · ") || "沒有變化欄位"}</small></div>) : <div className="empty">只有 change gate 通過時才建立 5 FPS 描述。</div>}</div><div><h3>語音轉錄（短期保存）</h3>{transcripts.length ? transcripts.slice(0, 5).map(item => <div className="transcript-row" key={item.id}><span>{formatDate(item.started_at)}</span><strong>{item.text || "—"}</strong><small>{item.language || "—"} · {Number(item.confidence || 0).toFixed(2)}</small></div>) : <div className="empty">目前沒有保存的語音文字。</div>}</div></div><div className="feed"><div className="subheading"><span>即時 feed</span><small>{liveFeed.length} items · session memory</small></div>{liveFeed.slice(0, 20).map(item => <div className="feed-row" key={item.id}><span className={`feed-icon ${item.kind || "neutral"}`} /> <strong>{item.title}</strong><span>{item.detail}</span><small>{formatDate(item.at)}</small></div>)}</div></Panel>;
}

function DiagnosticsPanel({ status, logs }: { status: Json | null; logs: Json[] }) {
  const services = status?.services || {};
  return <Panel title="執行狀態" eyebrow="OBSERVABILITY" className="diagnostics-panel"><div className="service-grid">{Object.entries(services).filter(([key]) => serviceNames[key]).map(([key, item]: [string, any]) => <div className="service-row" key={key}><span className={`service-dot ${item?.status || "unknown"}`} /><strong>{serviceNames[key]}</strong><Badge status={item?.status} /><small>{serviceSummary(item)}</small></div>)}</div><div className="log-list">{logs.slice(0, 10).map(log => <div className="log-line" key={log.id}><span>{formatDate(log.ts)}</span><Badge status={log.level} /><strong>{log.component}</strong><p>{log.message}</p></div>)}</div></Panel>;
}

function Setup({ onComplete }: { onComplete: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  async function complete() { setBusy(true); try { await onComplete(); } finally { setBusy(false); } }
  return <main className="setup-screen"><div className="setup-box"><div className="brand-mark">AC</div><div className="panel-eyebrow">CARE AGENT OS · FIRST RUN</div><h1>設定照護觀察環境</h1><p>目前使用 GMI Cloud MiniMax M3，從連續攝影機與麥克風建立有時間順序的觀察。姿態必須跨窗口確認後才會成為事件；只有有變化的窗口會送出分析。</p><div className="setup-points"><span><Badge status="healthy" /> HTTPS browser MediaStream</span><span><Badge status="healthy" /> 2 FPS × 5 秒變化 Gate</span><span><Badge status="healthy" /> SQLite 可追溯事件時間軸</span></div><div className="safety-note">模型輸出是觀察與假設，最終注意程度由程式政策裁決；不作診斷、治療或自動緊急服務。</div><button className="primary wide" disabled={busy} onClick={complete}>{busy ? "正在初始化…" : "進入觀察控制台"}</button></div></main>;
}

export function App() {
  const [setupDone, setSetupDone] = useState<boolean | null>(null);
  const [status, setStatus] = useState<Json | null>(null);
  const [events, setEvents] = useState<Json[]>([]);
  const [observation, setObservation] = useState<Json | null>(null);
  const [tracker, setTracker] = useState<Json | null>(null);
  const [scene, setScene] = useState<Json | null>(null);
  const [stream, setStream] = useState<Json | null>(null);
  const [descriptions, setDescriptions] = useState<Json[]>([]);
  const [changeGates, setChangeGates] = useState<Json[]>([]);
  const [transcripts, setTranscripts] = useState<Json[]>([]);
  const [agentRuns, setAgentRuns] = useState<Json[]>([]);
  const [agentTrace, setAgentTrace] = useState<Json[]>([]);
  const [logs, setLogs] = useState<Json[]>([]);
  const [liveFeed, setLiveFeed] = useState<Json[]>([]);
  const [error, setError] = useState("");
  const [lastRealtimeAt, setLastRealtimeAt] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [setup, currentStatus, currentEvents, descriptionsResult, gatesResult, transcriptResult, runsResult, traceResult, logsResult] = await Promise.all([
        api<Json>("/api/setup/status"), api<Json>("/api/status"), api<{ items: Json[] }>("/api/events?page_size=80"),
        api<{ items: Json[] }>("/api/media/descriptions?limit=30"), api<{ items: Json[] }>("/api/media/change-gates?limit=30"), api<{ items: Json[] }>("/api/transcripts/recent"),
        api<{ items: Json[] }>("/api/agent/runs?limit=20"), api<{ items: Json[] }>("/api/agent/events?limit=120"), api<{ items: Json[] }>("/api/logs?limit=50"),
      ]);
      setSetupDone(Boolean(setup.completed)); setStatus(currentStatus); setEvents(currentEvents.items); setDescriptions(descriptionsResult.items); setChangeGates(gatesResult.items);
      setTranscripts(transcriptResult.items); setAgentRuns(runsResult.items); setAgentTrace(traceResult.items); setLogs(logsResult.items);
      const active = currentStatus.source?.detail?.active_streams?.[0];
      if (active) { setStream(active); if (active.last_observation) setObservation(active.last_observation); if (active.state_tracker) setTracker(active.state_tracker); if (active.scene_context) setScene(active.scene_context); }
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "無法載入 backend"); }
  }, []);

  useEffect(() => { void refresh(); const timer = globalThis.setInterval(() => void refresh(), 4000); return () => globalThis.clearInterval(timer); }, [refresh]);

  useEffect(() => {
    let closed = false; let reconnectTimer: number | undefined; let socket: WebSocket | null = null;
    const addFeed = (item: Json) => setLiveFeed(previous => mergeById(previous, item));
    const connect = () => {
      if (closed) return; socket = new WebSocket(wsUrl());
      socket.onmessage = message => {
        try {
          const packet = JSON.parse(message.data); const payload = packet.payload || {}; setLastRealtimeAt(packet.occurred_at || new Date().toISOString());
          if (packet.type === "change_gate.completed") {
            if (payload.gate) setChangeGates(previous => mergeById(previous, payload.gate, 30));
            addFeed({ id: `gate-${packet.message_id}`, kind: payload.changed ? "accent" : "neutral", at: packet.occurred_at, title: "快速變化 Gate", detail: payload.change_summary || (payload.changed ? "有變化" : "無變化") });
          } else if (packet.type === "local_analysis.completed") {
            if (payload.observation) setObservation(payload.observation); if (payload.state_tracker) setTracker(payload.state_tracker); if (payload.scene_context) setScene(payload.scene_context);
            for (const item of [...(payload.events || []), ...(payload.recognition_events || [])]) setEvents(previous => mergeById(previous, item, 80));
            if (payload.transcript) setTranscripts(previous => mergeById(previous, payload.transcript, 30));
            addFeed({ id: `observation-${packet.message_id}`, kind: "observation", at: packet.occurred_at, title: "VLM 觀察完成", detail: `${postureLabel(payload.observation?.posture)} · ${formatOffset(payload.observation?.observed_at_offset_ms)}` });
          } else if (packet.type === "event.updated") {
            if (payload.event_type) setEvents(previous => mergeById(previous, payload, 80));
            addFeed({ id: `event-${packet.message_id}`, kind: toneForEvent(payload.event_type), at: packet.occurred_at, title: eventLabel(payload.event_type), detail: `${payload.status || "updated"} · ${formatOffset(payload.attributes_json?.occurred_offset_ms || payload.source_offset_ms)}` });
          } else if (packet.type.startsWith("agent.")) {
            if (payload.event) setAgentTrace(previous => mergeById(previous, payload.event, 120));
            if (packet.type === "agent.analysis.completed" && payload.agent_run) setAgentRuns(previous => mergeById(previous, payload.agent_run, 20));
            addFeed({ id: `agent-${packet.message_id}`, kind: "agent", at: packet.occurred_at, title: "主 Agent", detail: payload.message || packet.type });
          } else if (packet.type === "detail.description.completed" && payload.description) {
            setDescriptions(previous => mergeById(previous, payload.description, 30)); addFeed({ id: `detail-${packet.message_id}`, kind: "description", at: packet.occurred_at, title: "事件描述完成", detail: payload.description.description_text || "—" });
          } else if (packet.type === "audio.transcript") {
            setTranscripts(previous => mergeById(previous, payload, 30)); addFeed({ id: `audio-${packet.message_id}`, kind: "audio", at: packet.occurred_at, title: "語音轉錄完成", detail: payload.text || "—" });
          } else if (packet.type === "camera.status" && payload.services) {
            setStatus(previous => previous ? { ...previous, services: payload.services } : previous);
          } else if (packet.type === "warning.created") {
            addFeed({ id: `warning-${packet.message_id}`, kind: "urgent", at: packet.occurred_at, title: "需要注意", detail: payload.description || payload.next_action || "—" });
          }
        } catch { /* keep the persistent polling view intact */ }
      };
      socket.onclose = () => { if (!closed) reconnectTimer = globalThis.setTimeout(connect, 1200); };
    };
    reconnectTimer = globalThis.setTimeout(connect, 200);
    return () => { closed = true; if (reconnectTimer) globalThis.clearTimeout(reconnectTimer); socket?.close(); };
  }, []);

  async function run(label: string, operation: () => Promise<any>) { setError(""); try { await operation(); await refresh(); } catch (cause) { setError(cause instanceof Error ? cause.message : `${label} 失敗`); } }
  async function resetHistory() {
    if (!globalThis.confirm("確定要清除所有事件、Gate、描述、Agent trace、轉錄與執行 log 嗎？設定與模型安裝會保留。")) return;
    setError("");
    try {
      await api("/api/history/reset", { method: "POST" });
      setEvents([]); setDescriptions([]); setChangeGates([]); setTranscripts([]); setAgentRuns([]); setAgentTrace([]); setLogs([]); setLiveFeed([]); setObservation(null); setTracker(null); setScene(null);
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "清除歷史失敗"); }
  }
  async function completeSetup() { await api("/api/setup/complete", { method: "POST" }); setSetupDone(true); await refresh(); }
  if (setupDone === null) return <div className="loading-screen"><div><div className="brand-mark">AC</div><p>正在連線到 Care Agent backend…</p></div></div>;
  if (!setupDone) return <Setup onComplete={completeSetup} />;
  const services = status?.services || {}; const activeStream = stream || status?.source?.detail?.active_streams?.[0];
  return <main className="app-shell"><header className="app-header"><div className="brand-lockup"><div className="brand-mark">AC</div><div><div className="panel-eyebrow">AMBIENT CARE AGENT OS</div><h1>照護觀察控制台</h1><p>把短暫影像觀察轉成可驗證的時間事件</p></div></div><div className="header-right"><div className="connection"><span className="pulse" />{lastRealtimeAt ? `即時連線 · ${formatDate(lastRealtimeAt)}` : "等待即時連線"}</div><button className="danger" onClick={() => void resetHistory()}>重製並清除歷史</button></div></header>
    {error && <div className="global-error"><strong>系統訊息</strong>{error}</div>}
    <div className="service-strip">{Object.entries(serviceNames).map(([key, label]) => <div className="service-pill" key={key}><span className={`service-dot ${services[key]?.status || "unknown"}`} /><span>{label}</span><Badge status={services[key]?.status} /></div>)}</div>
    <div className="dashboard"><CapturePanel onUpdated={refresh} onStream={setStream} /><CurrentStatePanel observation={observation} tracker={tracker} scene={scene} stream={activeStream} /><TimelinePanel events={events} /><AgentPanel runs={agentRuns} trace={agentTrace} /><EvidencePanel observation={observation} descriptions={descriptions} transcripts={transcripts} changeGates={changeGates} liveFeed={liveFeed} /><DiagnosticsPanel status={status} logs={logs} /></div>
    <footer>CARE AGENT OS · persistent observation timeline · state tracker v1 · raw media is not shown as events</footer>
  </main>;
}
