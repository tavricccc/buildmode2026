import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { Badge, Card, ErrorBanner, errorText } from "../components/ui";
import type { PrivacyDimension, StatusReport } from "../types/api";

const DEFAULT_DIMENSIONS: PrivacyDimension[] = [
  { key: "sleep", name: "睡眠狀態", status: "資料不足", score: 5 },
  { key: "diet", name: "飲食狀態", status: "資料不足", score: 5 },
  { key: "exercise", name: "運動狀態", status: "資料不足", score: 5 },
  { key: "social", name: "社交狀態", status: "資料不足", score: 5 },
];

function PrivacyRadar({ dimensions }: { dimensions: PrivacyDimension[] }) {
  const ordered = DEFAULT_DIMENSIONS.map((fallback) => dimensions.find((item) => item.key === fallback.key) || fallback);
  const center = 120;
  const radius = 78;
  const point = (index: number, value: number, scale = radius) => {
    const angle = -Math.PI / 2 + (index * Math.PI) / 2;
    const distance = scale * Math.max(0, Math.min(10, value)) / 10;
    return `${center + Math.cos(angle) * distance},${center + Math.sin(angle) * distance}`;
  };
  const polygon = (scale: number) => [0, 1, 2, 3].map((index) => point(index, 10, scale)).join(" ");
  const values = ordered.map((item) => item.score || 5);
  const statusTone = (status: string) => status === "需要進一步確認" ? "warn" : status === "未見異常" ? "ok" : "muted";

  return (
    <div className="privacy-radar-layout">
      <svg className="privacy-radar" viewBox="0 0 240 240" role="img" aria-label="睡眠、飲食、運動、社交四面向狀態雷達圖">
        {[2.5, 5, 7.5, 10].map((scale) => <polygon key={scale} points={polygon(radius * scale / 10)} className="privacy-radar-grid" />)}
        {[0, 1, 2, 3].map((index) => <line key={index} x1={center} y1={center} x2={point(index, 10).split(",")[0]} y2={point(index, 10).split(",")[1]} className="privacy-radar-axis" />)}
        <polygon points={values.map((value, index) => point(index, value)).join(" ")} className="privacy-radar-value" />
        {values.map((value, index) => {
          const [x, y] = point(index, value).split(",").map(Number);
          return <circle key={index} cx={x} cy={y} r="3.5" className="privacy-radar-dot" />;
        })}
        <text x="120" y="13" textAnchor="middle">睡眠</text>
        <text x="228" y="124" textAnchor="end">飲食</text>
        <text x="120" y="236" textAnchor="middle">運動</text>
        <text x="12" y="124">社交</text>
      </svg>
      <div className="privacy-radar-legend">
        {ordered.map((item) => (
          <div className="privacy-dimension" key={item.key}>
            <div><strong>{item.name}</strong><b>{item.score}/10</b></div>
            <span className={`privacy-status ${statusTone(item.status)}`}>{item.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ReportsPage() {
  const [reports, setReports] = useState<StatusReport[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await api.statusReports();
      setReports(result.reports);
      setError(null);
    } catch (exc) {
      setError(errorText(exc));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const dimensions = reports[0]?.sources.privacy_dimensions || DEFAULT_DIMENSIONS;

  return (
    <div className="page-stack">
      <header className="page-heading">
        <div>
          <span className="eyebrow">SOCIAL WORK · PRIVACY SUMMARY</span>
          <h1>社工整體狀態</h1>
          <p>只提供四面向整體趨勢，協助社工掌握需要確認的方向。</p>
        </div>
      </header>

      {error && <ErrorBanner>{error}</ErrorBanner>}

      <Card title="四面向整體狀態" aside={<Badge tone="muted">1–10 抽象分數</Badge>}>
        <p className="privacy-note">分數僅作為狀態趨勢提示，不代表量表評估、醫療判斷或長者完成率；資料不足以 5/10 顯示，避免把未知誤讀為正常。</p>
        <PrivacyRadar dimensions={dimensions} />
      </Card>

      <Card title="社工頁面說明">
        <div className="privacy-statements">
          <p>本頁只呈現睡眠、飲食、運動、社交四面向的整體狀態。</p>
          <p>逐筆生活事件、逐字互動、精確量測與個人細節不在此頁顯示。</p>
          <p>需要進一步確認的項目，請依社工工作流程人工確認。</p>
        </div>
      </Card>
    </div>
  );
}
