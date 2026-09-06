import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bug, CircleNotch, Pause, Play, Pulse, Warning } from "@phosphor-icons/react";
import { api } from "../api/client";
import type { RealtimeClient } from "../api/ws";
import { Badge, Card, Empty, ErrorBanner, clock, errorText } from "../components/ui";
import type { Tone } from "../components/ui";
import type { DebugStatus, PipelineStep, Status } from "../types/api";

const STEP_LABELS: Record<string, string> = {
  source: "來源接收",
  l1_gate: "L1 人體判讀",
  l2_observation: "L2 情境觀察",
  state_machine: "事件狀態機",
  l3_review: "L3 深度覆核",
  policy_gateway: "Policy 授權",
  delivery: "通知與 Dashboard",
  persistence: "SQLite 稽核紀錄",
};

const STATUS_LABELS: Record<PipelineStep["status"], string> = {
  waiting: "等待中",
  running: "執行中",
  succeeded: "完成",
  skipped: "略過",
  degraded: "降級",
  failed: "失敗",
};

const tone = (status: PipelineStep["status"]): Tone =>
  status === "failed" ? "bad" : status === "degraded" || status === "waiting" ? "warn"
  : status === "succeeded" ? "ok" : "muted";

export function OperationsPage({ status, realtime }: { status: Status | null; realtime: RealtimeClient }) {
  const [steps, setSteps] = useState<PipelineStep[]>([]);
  const [debug, setDebug] = useState<DebugStatus | null>(null);
  const [paused, setPaused] = useState(false);
  const [abnormalOnly, setAbnormalOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [days, setDays] = useState(45);
  const [profile, setProfile] = useState("mixed");
  const [seed, setSeed] = useState(20260906);
  const [scenario, setScenario] = useState("fall_confirmed");
  const [simulationMode, setSimulationMode] = useState<"contract" | "evaluation">("contract");
  const pending = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    if (paused) return;
    try {
      const [data, debugData] = await Promise.all([
        api.activePipeline(),
        status?.runtime.debug ? api.debugStatus() : Promise.resolve(null),
      ]);
      setSteps(data.recent);
      setError(null);
      if (debugData) setDebug(debugData);
    } catch (exc) {
      setError(errorText(exc));
    }
  }, [paused, status?.runtime.debug]);

  useEffect(() => {
    void refresh();
    const schedule = () => {
      if (paused || pending.current !== null) return;
      pending.current = window.setTimeout(() => { pending.current = null; void refresh(); }, 250);
    };
    const offMessage = realtime.onMessage(schedule);
    const offResync = realtime.onResync(() => void refresh());
    return () => {
      offMessage(); offResync();
      if (pending.current !== null) window.clearTimeout(pending.current);
    };
  }, [paused, realtime, refresh]);

  const shown = useMemo(() => abnormalOnly
    ? steps.filter((step) => ["waiting", "degraded", "failed"].includes(step.status))
    : steps, [abnormalOnly, steps]);

  const runAction = async (action: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await action(); await refresh(); }
    catch (exc) { setError(errorText(exc)); }
    finally { setBusy(false); }
  };

  return <div className="page-stack operations-page">
    <header className="page-heading">
      <div><span className="eyebrow">系統即時狀態</span><h1>運作監看</h1><p>Production 為唯讀；Debug mode 另提供模擬控制。</p></div>
      <div className="button-row">
        {status?.runtime.debug && <Badge tone="warn" dot>DEBUG · 模擬資料</Badge>}
        <button className="action" onClick={() => setPaused((value) => !value)}>
          {paused ? <Play size={16} /> : <Pause size={16} />}{paused ? "繼續更新" : "暫停畫面"}
        </button>
      </div>
    </header>

    {error && <ErrorBanner>{error}</ErrorBanner>}
    <section className="operation-health">
      <div><span>來源</span><b>{status?.source.lifecycle === "completed" ? "錄影播放完成" : status?.source.running ? "接收中" : "未啟動"}</b></div>
      <div><span>L2 queue</span><b>{status?.cascade.l2.queue.running ? "執行中" : status?.cascade.l2.queue.pending ? "等待中" : "空閒"}</b></div>
      <div><span>L3 queue</span><b>{status?.cascade.l3.queue.running ? "執行中" : status?.cascade.l3.queue.pending ? "等待中" : "空閒"}</b></div>
      <div><span>更新</span><b>{paused ? "已暫停" : "即時"}</b></div>
    </section>

    {status?.runtime.debug && <Card title={<><Bug size={16} />Debug 控制</>} className="debug-controls">
      <div className="debug-grid">
        <div className="debug-block"><h3>歷史資料</h3>
          <label className="field"><span>天數</span><input type="number" min={1} max={90} value={days} onChange={(event) => setDays(Number(event.target.value))} /></label>
          <label className="field"><span>Profile</span><select value={profile} onChange={(event) => setProfile(event.target.value)}><option value="stable">穩定</option><option value="gradual-decline">逐步下降</option><option value="event-heavy">事件密集</option><option value="mixed">混合</option></select></label>
          <label className="field"><span>Seed</span><input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label>
          <button className="action" disabled={busy} onClick={() => void runAction(() => api.generateDebugHistory(days, profile, seed))}>產生歷史資料</button>
        </div>
        <div className="debug-block"><h3>手動情境</h3>
          <label className="field"><span>情境</span><select value={scenario} onChange={(event) => setScenario(event.target.value)}>{debug?.scenarios.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label className="field"><span>模式</span><select value={simulationMode} onChange={(event) => setSimulationMode(event.target.value as typeof simulationMode)}><option value="contract">Contract · 驗證下游</option><option value="evaluation">Evaluation · 不提供預期答案</option></select></label>
          <button className="action" disabled={busy} onClick={() => void runAction(() => api.triggerDebugScenario(scenario, simulationMode))}>觸發情境</button>
        </div>
        <div className="debug-block"><h3>即時隨機事件</h3><p className="muted">依固定 seed 持續產生事件，可重現同一串測試。</p>
          <Badge tone={debug?.stream.running ? "warn" : "muted"} dot>{debug?.stream.running ? `執行中 · ${debug.stream.events ?? 0} 件` : "未啟動"}</Badge>
          <div className="button-row"><button className="action" disabled={busy || debug?.stream.running} onClick={() => void runAction(() => api.startDebugStream(profile, seed, 12))}>開始</button><button className="action" disabled={busy || !debug?.stream.running} onClick={() => void runAction(() => api.stopDebugStream())}>停止</button></div>
        </div>
      </div>
    </Card>}

    <Card title="即時步驟" aside={<label className="inline-check"><input type="checkbox" checked={abnormalOnly} onChange={(event) => setAbnormalOnly(event.target.checked)} />只看異常</label>}>
      {!shown.length ? <Empty>{paused ? "目前畫面已暫停。" : "啟動影像來源後，這裡會逐步顯示管線運作。"}</Empty> : <div className="operation-timeline" aria-live="polite">
        {shown.map((step) => <article className={`operation-step ${step.status}`} key={step.step_id}>
          <div className="step-marker">{step.status === "running" ? <CircleNotch className="spin" size={18} /> : step.status === "failed" ? <Warning size={18} /> : <Pulse size={18} />}</div>
          <div className="step-copy"><div><b>{STEP_LABELS[step.step] ?? step.step}</b><Badge tone={tone(step.status)}>{STATUS_LABELS[step.status]}</Badge><time>{clock(step.started_at_ms)}</time></div><p>{step.summary}</p>
            {(step.reason_codes.length > 0 || Object.keys(step.output).length > 0) && <details><summary>技術細節</summary><code>{[...step.reason_codes, JSON.stringify(step.output)].filter(Boolean).join(" · ")}</code></details>}
          </div>
        </article>)}
      </div>}
    </Card>
  </div>;
}
