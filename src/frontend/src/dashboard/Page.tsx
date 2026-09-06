import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight, ClipboardText, Drop, Heartbeat, PersonSimpleWalk, ShieldCheck,
  VideoCamera, Warning,
} from "@phosphor-icons/react";
import type { AppTab } from "../App";
import { api } from "../api/client";
import type { RealtimeClient } from "../api/ws";
import { Badge, Card, Empty, ErrorBanner, clock, errorText, riskTone } from "../components/ui";
import type {
  CareAction, CareEvent, CareReviewPayload, CareSummary, HealthSample, ObserverRecord,
  StatisticsPayload, Status,
} from "../types/api";

type Period = 1 | 3 | 7 | 30;
type Hydration = { sessions: number; total_ml: number; target_ml: number; progress: number };

const PERIODS: Period[] = [1, 3, 7, 30];
const HEALTH_LABELS: Record<string, string> = {
  heart_rate: "心率",
  blood_oxygen: "血氧",
  spo2: "血氧",
  temperature: "體溫",
  body_temperature: "體溫",
  weight: "體重",
  respiratory_rate: "呼吸頻率",
  blood_pressure_systolic: "收縮壓",
  blood_pressure_diastolic: "舒張壓",
  blood_glucose: "血糖",
  steps: "步數",
};

const eventLabel = (event: CareEvent) => event.event_type === "fall" ? "跌倒事件" : "飲水紀錄";
const eventStatus = (status: string) => ({
  suspect: "待確認", confirmed: "已確認", recovering: "恢復中", resolved: "已解除",
  completed: "已完成", dismissed: "已排除", idle: "無事件",
}[status] ?? status);
const policyLabel = (status: string) => ({ not_requested: "未要求通知", authorised: "已授權通知", suppressed: "通知已抑制", dashboard_only: "僅建立頁面提醒" }[status] ?? status);
const deliveryLabel = (status: string) => ({ not_sent: "未發送", pending: "等待發送", sent: "已送達", acknowledged: "已確認", false_alarm: "已標記誤報", failed: "發送失敗" }[status] ?? status);
const actionReason = (action: CareAction) => action.rule === "l3_advisory_not_authorised"
  ? "AI 建議聯繫照護人員；目前僅顯示頁面提醒"
  : action.rule === "fall_confirmed" ? "系統已確認跌倒事件" : action.reason;

const observerTone = (record: ObserverRecord | null) =>
  record?.status === "anomaly" ? "bad"
  : record?.status === "attention" ? "warn"
  : record?.status === "stable" ? "ok" : "muted";

function Sparkline({ samples }: { samples: HealthSample[] }) {
  if (samples.length < 2) return <div className="sparkline-placeholder" />;
  const values = samples.map((sample) => sample.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || 1;
  const points = values.map((value, index) => {
    const x = values.length === 1 ? 0 : (index / (values.length - 1)) * 100;
    const y = 31 - ((value - min) / spread) * 25;
    return `${x},${y}`;
  }).join(" ");
  return <svg className="sparkline" viewBox="0 0 100 36" preserveAspectRatio="none" aria-hidden="true">
    <polyline points={points} fill="none" vectorEffect="non-scaling-stroke" />
  </svg>;
}

export function DashboardPage({ status, realtime, onNavigate }: {
  status: Status | null;
  realtime: RealtimeClient;
  onNavigate: (tab: AppTab) => void;
}) {
  const [days, setDays] = useState<Period>(7);
  const [data, setData] = useState<StatisticsPayload | null>(null);
  const [hydration, setHydration] = useState<Hydration | null>(null);
  const [health, setHealth] = useState<HealthSample[]>([]);
  const [events, setEvents] = useState<CareEvent[]>([]);
  const [actions, setActions] = useState<CareAction[]>([]);
  const [observer, setObserver] = useState<ObserverRecord | null>(null);
  const [review, setReview] = useState<CareReviewPayload | null>(null);
  const [careSummary, setCareSummary] = useState<CareSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const pending = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      api.statistics(days), api.hydration(), api.health(), api.events(100),
      api.actions(40), api.observerStatus(), api.careSummary(),
    ]);
    const [statistics, hydrationData, healthData, eventData, actionData, observerData, careSummaryData] = results;
    if (statistics.status === "fulfilled") { setData(statistics.value); setError(null); }
    else setError(errorText(statistics.reason));
    if (hydrationData.status === "fulfilled") setHydration(hydrationData.value);
    if (healthData.status === "fulfilled") setHealth(healthData.value.samples);
    if (eventData.status === "fulfilled") setEvents(eventData.value.events);
    if (actionData.status === "fulfilled") setActions(actionData.value.actions);
    if (observerData.status === "fulfilled") setObserver(observerData.value.latest);
    if (careSummaryData.status === "fulfilled") setCareSummary(careSummaryData.value);
  }, [days]);

  useEffect(() => {
    void refresh();
    const schedule = () => {
      if (pending.current !== null) return;
      pending.current = window.setTimeout(() => { pending.current = null; void refresh(); }, 400);
    };
    const offMessage = realtime.onMessage(schedule);
    const offResync = realtime.onResync(() => void refresh());
    return () => {
      offMessage();
      offResync();
      if (pending.current !== null) window.clearTimeout(pending.current);
    };
  }, [refresh, realtime]);

  const since = Date.now() - days * 86_400_000;
  const periodEvents = events.filter((event) => event.occurred_at_ms >= since);
  const unsafe = periodEvents.some((event) => event.event_type === "fall" && ["suspect", "confirmed", "recovering"].includes(event.status));
  const sourceStarved = status?.cascade.starved_since_ms !== null;
  const stateLabel = careSummary?.headline ?? (sourceStarved ? "影像中斷" : unsafe ? "需要注意" : "資料不足，暫時無法判讀");
  const stateTone = careSummary?.urgency === "immediate" ? "bad"
    : ["today", "watch", "unknown"].includes(careSummary?.urgency ?? "unknown") ? "warn" : "ok";
  const summaries = data?.summaries ?? [];
  const totals = summaries.reduce((sum, day) => ({
    hydration: sum.hydration + Number(day.hydration_ml || 0),
    falls: sum.falls + Number(day.fall_events || 0),
    activity: sum.activity + Number(day.payload.activity_ratio || 0),
  }), { hydration: 0, falls: 0, activity: 0 });
  const activity = summaries.length ? Math.round((totals.activity / summaries.length) * 100) : 0;
  const fallCount = Math.max(totals.falls, periodEvents.filter((event) => event.event_type === "fall").length);
  const currentPosture = observer?.metrics.current_posture ?? "未知";
  const confidence = Math.round((observer?.confidence ?? 0) * 100);
  const unsuppressedActions = actions.filter((action) => !action.suppressed).slice(0, 4);

  const healthSeries = useMemo(() => {
    const grouped = new Map<string, HealthSample[]>();
    for (const sample of data?.health_samples ?? []) {
      const list = grouped.get(sample.metric) ?? [];
      list.push(sample);
      grouped.set(sample.metric, list);
    }
    return grouped;
  }, [data]);

  const analyze = async () => {
    setBusy(true);
    setReviewError(null);
    try {
      setReview(await api.analyzeAll(days));
      await refresh();
    } catch (exc) {
      setReviewError(errorText(exc));
    } finally {
      setBusy(false);
    }
  };

  if (!status) return <div className="page-stack"><Card title="照護總覽"><Empty>正在連線至後端…</Empty></Card></div>;

  return <div className="page-stack dashboard-page">
    <header className="care-hero">
      <div className="resident-title"><span className="eyebrow">住民照護總覽</span><h1>{status.subject_id}</h1><p>最後更新 {new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</p></div>
      <div className={`care-state ${stateTone}`}><ShieldCheck size={30} weight="fill" /><div><span>目前狀態</span><b>{stateLabel}</b><small>{careSummary?.recommended_next_step ?? "等待第一筆觀察資料"}</small></div></div>
      <button className="source-quick" onClick={() => onNavigate("source")}><VideoCamera size={20} /><div><span>即時影像</span><b>{status.source.lifecycle === "completed" ? "錄影播放完成" : status.source.running ? "分析中" : "尚未啟動"}</b></div><ArrowRight size={16} /></button>
    </header>

    <div className="dashboard-toolbar">
      <div><span className="toolbar-label">查看期間</span><div className="segmented compact period-switcher">
        {PERIODS.map((period) => <button key={period} aria-selected={days === period} onClick={() => setDays(period)}>{period}d</button>)}
      </div></div>
      <button className="action review-button" disabled={busy} onClick={() => void analyze()}>
        <ClipboardText size={18} />{busy ? "正在更新評估…" : "更新照護評估"}
      </button>
    </div>

    {sourceStarved && <div className="global-alert"><b>影像來源已停止提供畫面</b><span>目前安全狀態不可由舊資料推斷，請先檢查即時影像。</span></div>}
    {error && <ErrorBanner>無法讀取照護趨勢：{error}</ErrorBanner>}
    {reviewError && <ErrorBanner>L3 分析未完成：{reviewError}</ErrorBanner>}

    {careSummary && ["immediate", "today", "watch"].includes(careSummary.urgency) && <section className={`intervention-card ${careSummary.urgency}`} role="status">
      <div><span className="eyebrow">介入建議</span><h2>{careSummary.headline}</h2><p>{careSummary.recommended_next_step}</p></div>
      <div className="intervention-meta"><Badge tone={stateTone === "bad" ? "bad" : "warn"} dot>{careSummary.urgency === "immediate" ? "立即介入" : careSummary.urgency === "today" ? "今日處理" : "持續留意"}</Badge><span>信心 {Math.round(careSummary.confidence * 100)}%</span><span>Policy：{policyLabel(careSummary.policy_status)}</span><span>通知：{deliveryLabel(careSummary.delivery_status)}</span></div>
      {careSummary.reasons.length > 0 && <ul>{careSummary.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
      <small>AI 建議、Policy 授權與通知送達是三個不同狀態；此資訊不是醫療診斷。</small>
    </section>}

    <section className="care-metrics" aria-label={`最近 ${days} 天照護摘要`}>
      <div className="care-metric hydration"><span className="metric-icon"><Drop size={22} weight="fill" /></span><div><small>{days === 1 ? "今日飲水" : `${days} 天飲水`}</small><b>{Math.round(days === 1 && hydration ? hydration.total_ml : totals.hydration)} <em>ml</em></b><span>{days === 1 && hydration ? `${Math.round(hydration.progress * 100)}% 日目標` : `${summaries.length} 天有彙總`}</span></div></div>
      <div className="care-metric activity"><span className="metric-icon"><PersonSimpleWalk size={22} weight="fill" /></span><div><small>平均活動比例</small><b>{activity || "—"}{activity ? <em>%</em> : null}</b><span>依可用影像觀察估算</span></div></div>
      <div className={`care-metric falls ${fallCount ? "attention" : ""}`}><span className="metric-icon"><Warning size={22} weight="fill" /></span><div><small>跌倒相關事件</small><b>{fallCount}</b><span>{fallCount ? "請查看事件與照護紀錄" : "所選期間未記錄"}</span></div></div>
      <div className="care-metric posture"><span className="metric-icon"><Heartbeat size={22} weight="fill" /></span><div><small>最近觀察姿勢</small><b>{currentPosture}</b><span>{confidence ? `判讀信心 ${confidence}%` : "尚無可用信心值"}</span></div></div>
    </section>

    {review && <section className="l3-review" aria-live="polite">
      <div className="review-heading"><div><span className="eyebrow">照護評估 · {review.days} 天</span><h2>{review.analysis.summary}</h2></div><Badge tone={riskTone(review.analysis.risk_level)} dot>{review.analysis.risk_level} risk</Badge></div>
      <div className="review-columns">
        <div><h3>建議</h3>{review.analysis.recommendations.length ? <ul>{review.analysis.recommendations.map((item) => <li key={item}>{item}</li>)}</ul> : <p>目前沒有額外建議。</p>}</div>
        <div><h3>需要留意</h3>{review.analysis.attention_items.length ? <ul>{review.analysis.attention_items.map((item) => <li key={item}>{item}</li>)}</ul> : <p>沒有從資料中發現新的警訊。</p>}</div>
        <div><h3>正向訊號</h3>{review.analysis.positive_signals.length ? <ul>{review.analysis.positive_signals.map((item) => <li key={item}>{item}</li>)}</ul> : <p>目前資料不足以列出正向訊號。</p>}</div>
      </div>
      <footer><span>信心 {Math.round(review.analysis.confidence * 100)}% · {review.model}</span><span>資料範圍：{review.data_counts.daily_summaries} 日彙總、{review.data_counts.health_measurements} 筆健康量測、{review.data_counts.care_events} 件事件</span><small>此結果供照護判讀參考，不是醫療診斷，也不會直接觸發通知。</small></footer>
    </section>}

    <div className="content-grid care-content-grid">
      <Card title="健康量測" aside={<span className="muted">最近一筆與期間走勢</span>} className="span-8">
        {!health.length ? <Empty>尚無健康量測。可由穿戴裝置或健康資料 API 匯入。</Empty> : <div className="health-grid">
          {health.slice(0, 6).map((sample) => <div className="health-tile" key={sample.metric}>
            <div><span>{HEALTH_LABELS[sample.metric] ?? sample.metric.replaceAll("_", " ")}</span><small>{sample.source}</small></div>
            <b>{sample.value}<em>{sample.unit}</em></b>
            <Sparkline samples={healthSeries.get(sample.metric) ?? []} />
            <time>{clock(sample.observed_at_ms)} 更新</time>
          </div>)}
        </div>}
      </Card>

      <Card title="長期趨勢觀察" className="span-4 observer-card">
        {!observer ? <Empty>Observer 尚未建立紀錄。</Empty> : <>
          <Badge tone={observerTone(observer)} dot>{observer.status}</Badge>
          <h3>{observer.headline}</h3><p>{observer.detail}</p>
          <div className="observer-facts"><span>資料完整度 <b>{Math.round(observer.data_completeness * 100)}%</b></span><span>分析模式 <b>{observer.mode === "l3_narrative" ? "L3" : "規則彙總"}</b></span></div>
          <button className="text-action" onClick={() => onNavigate("statistics")}>查看完整觀察紀錄 <ArrowRight size={15} /></button>
        </>}
      </Card>

      <Card title="活動與飲水趨勢" aside={<button className="text-action" onClick={() => onNavigate("statistics")}>完整趨勢 <ArrowRight size={14} /></button>} className="span-8">
        {!summaries.length ? <Empty>累積一天資料後會出現趨勢。</Empty> : <div className="care-trend">
          {[...summaries].reverse().map((day) => {
            const dayActivity = Math.round(Number(day.payload.activity_ratio ?? 0) * 100);
            const hydrationPercent = Math.min(100, Math.round((Number(day.hydration_ml || 0) / (hydration?.target_ml || 1500)) * 100));
            return <div className="care-trend-row" key={day.day_key}><time>{day.day_key.slice(5)}</time><div><span>活動</span><i><b style={{ width: `${dayActivity}%` }} /></i><em>{dayActivity}%</em></div><div><span>飲水</span><i><b style={{ width: `${hydrationPercent}%` }} /></i><em>{Math.round(day.hydration_ml)} ml</em></div></div>;
          })}
        </div>}
      </Card>

      <Card title="近期照護事件" className="span-4">
        {!periodEvents.length && !unsuppressedActions.length ? <Empty>所選期間沒有需要處理的事件。</Empty> : <div className="care-event-list">
          {periodEvents.slice(0, 5).map((event) => <div key={event.event_id}><span className={`event-dot ${event.event_type === "fall" ? "bad" : "ok"}`} /><div><b>{eventLabel(event)}</b><span>{eventStatus(event.status)} · 信心 {Math.round(event.confidence * 100)}%</span></div><time>{clock(event.occurred_at_ms)}</time></div>)}
          {unsuppressedActions.slice(0, Math.max(0, 5 - periodEvents.length)).map((action) => <div key={action.action_id}><span className="event-dot warn" /><div><b>照護提醒</b><span>{actionReason(action)}</span></div><time>{clock(action.created_at)}</time></div>)}
        </div>}
      </Card>
    </div>
  </div>;
}
