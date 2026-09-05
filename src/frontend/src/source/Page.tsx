import { useEffect, useState } from "react";
import { ArrowClockwise, Play, Stop, VideoCamera } from "@phosphor-icons/react";
import { api } from "../api/client";
import { Badge, Card, Empty, ErrorBanner, errorText, ms } from "../components/ui";
import type { Status } from "../types/api";

type Scenario = { id: string; name: string; description: string };

export function SourcePage({ status }: { status: Status | null }) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [mode, setMode] = useState<"rtsp" | "replay_scenario" | "replay_file">("rtsp");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState(api.sourceSnapshotUrl());

  const source = status?.source;
  const running = source?.running ?? false;
  const completed = source?.lifecycle === "completed";
  const failed = source?.lifecycle === "failed";
  const sourceLabel = completed ? "錄影播放完成" : failed ? "來源失敗" : running ? "分析中" : "未啟動";

  useEffect(() => {
    void api.scenarios().then((data) => setScenarios(data.scenarios)).catch(() => undefined);
  }, []);

  // Only poll while frames are actually arriving; an idle install has no
  // snapshot to fetch and the <img> is not mounted anyway.
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setSnapshot(api.sourceSnapshotUrl()), 2000);
    return () => window.clearInterval(timer);
  }, [running]);

  const start = async (kind: string, value: string) => {
    setBusy(true); setMessage(null); setError(null);
    if (!value) {
      setError("請先選擇或輸入來源，再啟動分析。");
      setBusy(false);
      return;
    }
    try {
      await api.startSource(kind, value);
      setMessage("影像來源已啟動，分析管線正在接收畫面。");
    } catch (exc) {
      setError(errorText(exc));
    } finally { setBusy(false); }
  };

  const stop = async () => {
    setBusy(true); setMessage(null); setError(null);
    try { await api.stopSource(); setMessage("影像來源已停止。"); }
    catch (exc) { setError(errorText(exc)); }
    finally { setBusy(false); }
  };

  return (
    <div className="page-stack">
      <header className="page-heading">
        <div><span className="eyebrow">影像來源</span><h1>即時影像</h1><p>RTSP、模擬情境與本機錄影共用同一條分析管線。</p></div>
        <Badge tone={failed ? "bad" : completed ? "muted" : running ? "ok" : "muted"} dot>{sourceLabel}</Badge>
      </header>

      <div className="source-layout">
        <Card className="preview-card">
          <div className="preview-frame">
            {running || completed ? <img src={snapshot} alt={completed ? "錄影最後一個分析影格" : "最新分析影格"} /> : (
              <div className="preview-empty"><VideoCamera size={38} /><b>尚未接收影像</b><span>啟動來源後顯示最新取樣影格</span></div>
            )}
            <div className="preview-label"><i className={`status-dot ${failed ? "bad" : running ? "ok" : "muted"}`} />{completed ? "錄影播放完成 · 最後影格" : "分析用低頻預覽"}</div>
          </div>
          <div className="source-metrics">
            <span><b>{source?.kind ?? "—"}</b>來源</span>
            <span><b>{source?.frames_emitted ?? 0}</b>已接收影格</span>
            <span><b>{source?.last_frame_age_ms == null ? "—" : ms(source.last_frame_age_ms)}</b>最後影格</span>
            <span><b>{source?.reconnects ?? 0}</b>重新連線</span>
          </div>
          {source?.error && <p className="banner bad">來源錯誤：{source.error}</p>}
        </Card>

        <Card title="選擇來源" className="source-control-card">
          <div className="segmented" role="tablist" aria-label="來源類型">
            <button aria-selected={mode === "rtsp"} onClick={() => setMode("rtsp")}>即時鏡頭</button>
            <button aria-selected={mode === "replay_scenario"} onClick={() => setMode("replay_scenario")}>模擬情境</button>
            <button aria-selected={mode === "replay_file"} onClick={() => setMode("replay_file")}>本機錄影</button>
          </div>
          {mode === "rtsp" && <label className="field"><span>RTSP 位址</span><input type="password" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="rtsp://攝影機位址（不會回傳至瀏覽器）" /></label>}
          {mode === "replay_file" && <label className="field"><span>主機上的影片路徑</span><input value={target} onChange={(e) => setTarget(e.target.value)} placeholder="C:\\care-data\\sample.mp4" /></label>}
          {mode === "replay_scenario" && <div className="scenario-list">
            {scenarios.length === 0 ? <Empty>沒有可用的模擬情境。</Empty> : scenarios.map((scenario) => (
              <button key={scenario.id} onClick={() => setTarget(scenario.id)} aria-pressed={target === scenario.id}>
                <b>{scenario.name}</b><span>{scenario.description || "驗證完整 Cascade 行為"}</span>
              </button>
            ))}
          </div>}
          <div className="button-row">
            <button className="action primary" disabled={busy || !target} onClick={() => void start(mode, target)}><Play size={17} weight="fill" />開始分析</button>
            <button className="action" disabled={busy || !running} onClick={() => void stop()}><Stop size={17} weight="fill" />停止</button>
            <button className="action ghost" disabled={busy || !running || !target}
                    title={running && !target ? "重新連線需要先在上方指定來源" : undefined}
                    onClick={() => void start(mode, target)}><ArrowClockwise size={17} />重新連線</button>
          </div>
          {error && <ErrorBanner>{error}</ErrorBanner>}
          {message && <p className="banner">{message}</p>}
          <p className="privacy-note">此畫面僅顯示分析 Ring Buffer 的最新取樣影格，不是錄影儲存或 NVR。</p>
        </Card>
      </div>
    </div>
  );
}
