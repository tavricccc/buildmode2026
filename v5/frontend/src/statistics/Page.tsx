import { useCallback, useEffect, useState } from "react";
import { ArrowClockwise, Brain, Drop, PersonSimpleWalk, Warning } from "@phosphor-icons/react";
import { api } from "../api/client";
import { Badge, Card, Empty, clock } from "../components/ui";
import type { ObserverRecord, StatisticsPayload } from "../types/api";

const tone = (status: ObserverRecord["status"]) => status === "anomaly" ? "bad" : status === "attention" ? "warn" : status === "stable" ? "ok" : "muted";

export function StatisticsPage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<StatisticsPayload | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => setData(await api.statistics(days)), [days]);
  useEffect(() => { void load(); }, [load]);

  const runNow = async () => {
    setBusy(true);
    try { await api.runObserver(); await load(); } finally { setBusy(false); }
  };

  const latest = data?.recent_observations[0];
  const totals = (data?.summaries ?? []).reduce((sum, day) => ({
    hydration: sum.hydration + Number(day.hydration_ml || 0),
    falls: sum.falls + Number(day.fall_events || 0),
    l2: sum.l2 + Number(day.l2_calls || 0),
    l3: sum.l3 + Number(day.l3_calls || 0),
  }), { hydration: 0, falls: 0, l2: 0, l3: 0 });

  return <div className="page-stack">
    <header className="page-heading">
      <div><span className="eyebrow">Long-term Observer</span><h1>趨勢與統計</h1><p>定期讀取 SQLite 彙總；正常狀態同樣留下可稽核紀錄。</p></div>
      <div className="button-row">
        <div className="segmented compact">{[7, 30, 90].map((value) => <button key={value} aria-selected={days === value} onClick={() => setDays(value)}>{value} 天</button>)}</div>
        <button className="action" disabled={busy} onClick={() => void runNow()}><ArrowClockwise size={17} />立即分析</button>
      </div>
    </header>

    <div className="metric-grid">
      <div className="metric-tile"><Drop size={21} /><span>期間飲水</span><b>{Math.round(totals.hydration)} ml</b></div>
      <div className="metric-tile"><Warning size={21} /><span>跌倒事件</span><b>{totals.falls}</b></div>
      <div className="metric-tile"><PersonSimpleWalk size={21} /><span>L2 觀察</span><b>{totals.l2}</b></div>
      <div className="metric-tile"><Brain size={21} /><span>L3 深度分析</span><b>{totals.l3}</b></div>
    </div>

    <div className="content-grid stats-grid">
      <Card title="每日趨勢" className="span-8">
        {!data?.summaries.length ? <Empty>累積一天資料後會出現趨勢。</Empty> : <div className="trend-list">
          {data.summaries.map((day) => {
            const activity = Math.round(Number(day.payload.activity_ratio ?? 0) * 100);
            return <div className="trend-row" key={day.day_key}>
              <time>{day.day_key}</time>
              <div><span>活動</span><progress max="100" value={activity} /><b>{activity}%</b></div>
              <div><span>飲水</span><progress max="1500" value={day.hydration_ml} /><b>{Math.round(day.hydration_ml)} ml</b></div>
              <Badge tone={day.fall_events ? "bad" : "ok"}>{day.fall_events ? `${day.fall_events} 次跌倒事件` : "未發現跌倒"}</Badge>
            </div>;
          })}
        </div>}
      </Card>
      <Card title="AI 身體狀況" className="span-4 observer-summary">
        {!latest ? <Empty>尚無分析紀錄。</Empty> : <>
          <Badge tone={tone(latest.status)} dot>{latest.status === "stable" ? "狀況穩定" : latest.status === "insufficient_evidence" ? "資料不足" : "需要注意"}</Badge>
          <h3>{latest.headline}</h3><p>{latest.detail}</p>
          <dl><div><dt>目前姿勢</dt><dd>{latest.metrics.current_posture ?? "未知"}</dd></div><div><dt>分析信心</dt><dd>{Math.round(latest.confidence * 100)}%</dd></div><div><dt>資料完整度</dt><dd>{Math.round(latest.data_completeness * 100)}%</dd></div></dl>
          <small>AI 觀察不是醫療診斷。</small>
        </>}
      </Card>
    </div>

    <Card title="持續觀測紀錄" aside={<span className="muted">正常結果也會保留</span>}>
      {!data?.recent_observations.length ? <Empty>Observer 尚未完成第一次分析。</Empty> : <div className="observation-list">
        {data.recent_observations.map((record) => <div key={record.observer_run_id}>
          <time className="mono">{clock(record.window_ended_at_ms)}</time><Badge tone={tone(record.status)}>{record.status}</Badge>
          <div><b>{record.headline}</b><span>{record.detail}</span></div><small>{record.mode === "l3_narrative" ? "L3 解讀" : "規則彙總"} · 完整度 {Math.round(record.data_completeness * 100)}%</small>
        </div>)}
      </div>}
    </Card>
  </div>;
}
