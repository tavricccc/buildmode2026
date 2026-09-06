import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { Badge, Card, Empty, ErrorBanner, errorText } from "../components/ui";
import type { PrivacyDimension, SocialWorkRecord, StatusReport } from "../types/api";

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
  const [records, setRecords] = useState<SocialWorkRecord[]>([]);
  const [reports, setReports] = useState<StatusReport[]>([]);
  const [recordType, setRecordType] = useState("case_note");
  const [author, setAuthor] = useState("");
  const [content, setContent] = useState("");
  const [tags, setTags] = useState("");
  const [reportType, setReportType] = useState("daily_status");
  const [days, setDays] = useState(7);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Auto-generation state
  const [autoHours, setAutoHours] = useState(24);
  const [autoAuthor, setAutoAuthor] = useState("AI 社工助理 (事件自動彙整)");
  const [autoNotice, setAutoNotice] = useState<string | null>(null);
  const [filterMode, setFilterMode] = useState<"all" | "auto" | "manual">("all");

  const load = useCallback(async () => {
    try {
      const [recordData, reportData] = await Promise.all([api.socialWorkRecords(), api.statusReports()]);
      setRecords(recordData.records);
      setReports(reportData.reports);
      setError(null);
    } catch (exc) {
      setError(errorText(exc));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const saveRecord = async () => {
    if (!content.trim()) return;
    setBusy(true);
    try {
      await api.addSocialWorkRecord({
        record_type: recordType,
        occurred_at_ms: Date.now(),
        author,
        content: content.trim(),
        tags: tags.split(",").map((item) => item.trim()).filter(Boolean),
      });
      setContent("");
      setTags("");
      await load();
    } catch (exc) {
      setError(errorText(exc));
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    setBusy(true);
    try {
      await api.generateStatusReport(reportType, days);
      await load();
    } catch (exc) {
      setError(errorText(exc));
    } finally {
      setBusy(false);
    }
  };

  const autoGenerateLog = async () => {
    setBusy(true);
    setAutoNotice(null);
    try {
      await api.autoGenerateSocialWorkRecord(autoHours, "case_note", autoAuthor);
      setAutoNotice(
        `✅ 已產生過去 ${autoHours} 小時的隱私摘要，僅保留整體狀態、運動／用藥／作息抽象警示與待確認事項，並已同步歸檔。`
      );
      await load();
    } catch (exc) {
      setError(errorText(exc));
    } finally {
      setBusy(false);
    }
  };

  const filteredRecords = records.filter((r) => {
    const isAuto = r.tags.some((t) => t.includes("自動彙整") || t.includes("社工日誌") || t.includes("SOAP"));
    if (filterMode === "auto") return isAuto;
    if (filterMode === "manual") return !isAuto;
    return true;
  });

  return (
    <div className="page-stack">
      <header className="page-heading">
        <div>
          <span className="eyebrow">SOCIAL WORK · AUDITABLE SOURCES</span>
          <h1>社工日誌與狀態報告</h1>
          <p>產出供社工覆核的整體狀態摘要。日誌不展開生活起居、逐字互動、精確數值或完成次數，只保留運動、用藥、作息的抽象警示與需要進一步確認的事項。</p>
        </div>
      </header>

      {error && <ErrorBanner>{error}</ErrorBanner>}

      {/* 核心功能：讀取事件自動產生社工日誌 */}
      <Card
        title="⚡ 產生隱私摘要 · 社工日誌"
        aside={<Badge tone="ok">社工覆核前草稿</Badge>}
      >
        <p style={{ margin: "0 0 14px 0", color: "var(--muted)", fontSize: "0.95rem", lineHeight: 1.6 }}>
          系統只把受控資料轉成<b>整體狀態</b>、<b>運動／用藥／作息警示</b>與<b>待確認事項</b>。逐筆生活事件、飲食／飲水完成紀錄、逐字互動、精確量測與模型分數不會寫入社工日誌。
        </p>

        <div style={{ display: "flex", gap: "14px", alignItems: "flex-end", flexWrap: "wrap", marginBottom: "12px" }}>
          <label className="field" style={{ minWidth: "180px", flex: "1" }}>
            <span>統計事件時段</span>
            <select
              value={autoHours}
              onChange={(event) => setAutoHours(Number(event.target.value) || 24)}
              disabled={busy}
            >
              <option value={12}>過去 12 小時（白班/夜班巡檢）</option>
              <option value={24}>過去 24 小時（今日社工日常日誌）</option>
              <option value={48}>過去 48 小時（雙日巡護總結）</option>
              <option value={72}>過去 72 小時（三日照護觀察）</option>
              <option value={168}>過去 7 天（一週綜合個案報告）</option>
            </select>
          </label>

          <label className="field" style={{ minWidth: "220px", flex: "1" }}>
            <span>產出紀錄者署名</span>
            <input
              value={autoAuthor}
              onChange={(event) => setAutoAuthor(event.target.value)}
              placeholder="社工或系統名稱"
              disabled={busy}
            />
          </label>

          <button
            className="action primary"
            style={{ height: "42px", padding: "0 24px", fontWeight: "600" }}
            disabled={busy}
            onClick={() => void autoGenerateLog()}
          >
            {busy ? "隱私摘要產生中…" : "⚡ 產生隱私摘要社工日誌"}
          </button>
        </div>

        {autoNotice && <p className="banner" style={{ marginTop: "12px", background: "rgba(16, 185, 129, 0.15)", border: "1px solid rgba(16, 185, 129, 0.4)", color: "#10b981", padding: "10px 14px", borderRadius: "6px" }}>{autoNotice}</p>}
      </Card>

      <Card title="四面向整體狀態" aside={<Badge tone="muted">1–10 抽象分數</Badge>}>
        <p className="privacy-note">分數只作為狀態趨勢提示，不代表量表評估或長者完成率；「資料不足」以 5/10 顯示，避免把未知誤讀為正常。</p>
        <PrivacyRadar dimensions={reports[0]?.sources.privacy_dimensions || DEFAULT_DIMENSIONS} />
      </Card>

      <div className="interaction-grid">
        <Card title="新增手動社工紀錄">
          <div className="grid cols-2">
            <label className="field">
              <span>服務類型</span>
              <select value={recordType} onChange={(event) => setRecordType(event.target.value)}>
                <option value="visit">訪視</option>
                <option value="phone">電話關懷</option>
                <option value="case_note">個案紀錄</option>
                <option value="follow_up">追蹤</option>
                <option value="resource_referral">資源轉介</option>
              </select>
            </label>
            <label className="field">
              <span>紀錄者</span>
              <input value={author} onChange={(event) => setAuthor(event.target.value)} placeholder="社工姓名或代號" />
            </label>
          </div>
          <label className="field">
            <span>紀錄內容</span>
            <textarea value={content} onChange={(event) => setContent(event.target.value)} placeholder="只填需要進一步確認或已人工確認的事項，不填生活起居細節。" />
          </label>
          <label className="field">
            <span>標籤（逗號分隔）</span>
            <input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="家訪, 資源連結" />
          </label>
          <button className="action primary" disabled={busy || !content.trim()} onClick={() => void saveRecord()}>儲存社工紀錄</button>
        </Card>

        <Card title="產生狀態摘要報告">
          <label className="field">
            <span>報告類型</span>
            <select value={reportType} onChange={(event) => setReportType(event.target.value)}>
              <option value="daily_status">日常狀態</option>
              <option value="follow_up">追蹤</option>
              <option value="case_summary">個案摘要</option>
            </select>
          </label>
          <label className="field">
            <span>查詢期間（天）</span>
            <input type="number" min="1" max="90" value={days} onChange={(event) => setDays(Number(event.target.value) || 7)} />
          </label>
          <button className="action primary" disabled={busy} onClick={() => void generate()}>產生可覆核初稿</button>
          <p className="privacy-note">沒有社工紀錄時，報告會明確標示資料不足，不會由模型補寫成事實。</p>
        </Card>
      </div>

      <Card
        title="社工紀錄庫"
        aside={
          <div style={{ display: "flex", gap: "6px" }}>
            <button
              className={`action ${filterMode === "all" ? "primary" : "ghost"}`}
              style={{ padding: "4px 10px", fontSize: "0.85rem" }}
              onClick={() => setFilterMode("all")}
            >
              全部 ({records.length})
            </button>
            <button
              className={`action ${filterMode === "auto" ? "primary" : "ghost"}`}
              style={{ padding: "4px 10px", fontSize: "0.85rem" }}
              onClick={() => setFilterMode("auto")}
            >
              ⚡ 自動產生日誌 ({records.filter((r) => r.tags.some((t) => t.includes("自動彙整") || t.includes("社工日誌") || t.includes("SOAP"))).length})
            </button>
            <button
              className={`action ${filterMode === "manual" ? "primary" : "ghost"}`}
              style={{ padding: "4px 10px", fontSize: "0.85rem" }}
              onClick={() => setFilterMode("manual")}
            >
              ✍️ 手動備忘 ({records.filter((r) => !r.tags.some((t) => t.includes("自動彙整") || t.includes("社工日誌") || t.includes("SOAP"))).length})
            </button>
          </div>
        }
      >
        <div className="record-list">
          {filteredRecords.length ? (
            filteredRecords.map((record) => {
              const isAuto = record.tags.some((t) => t.includes("自動彙整") || t.includes("社工日誌") || t.includes("SOAP"));
              return (
                <article className="audit-entry" key={record.record_id} style={isAuto ? { borderLeft: "4px solid #10b981", background: "rgba(16, 185, 129, 0.04)" } : undefined}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", marginBottom: "6px" }}>
                    {isAuto && <Badge tone="ok">⚡ AI 自動彙整</Badge>}
                    <Badge tone="muted">{record.record_type}</Badge>
                    <strong>{record.author || "未署名"}</strong>
                    <small>{new Date(record.occurred_at_ms).toLocaleString()}</small>
                  </div>
                  <p className="privacy-note" style={{ margin: "8px 0" }}>內容已隱去；請以狀態摘要與待確認事項進行人工覆核。</p>
                  <small style={{ color: "var(--muted)" }}>標籤：{record.tags.join(" · ") || "無"} · 隱私保護</small>
                </article>
              );
            })
          ) : (
            <Empty>尚無符合條件之社工紀錄。點擊上方「產生隱私摘要社工日誌」即可一鍵生成。</Empty>
          )}
        </div>
      </Card>

      <Card title="已產生之狀態報告">
        <div className="record-list">
          {reports.length ? (
            reports.map((report) => (
              <article className="audit-entry" key={report.report_id}>
                <h3>{report.title}</h3>
                <small>{new Date(report.window_start_ms).toLocaleDateString()} 至 {new Date(report.window_end_ms).toLocaleDateString()} · {report.report_type}</small>
                <pre style={{ whiteSpace: "pre-wrap", margin: "10px 0" }}>{report.body}</pre>
                <small>來源已保留於受控稽核層；此頁不展開原始內容。</small>
              </article>
            ))
          ) : (
            <Empty>尚未產生報告。</Empty>
          )}
        </div>
      </Card>
    </div>
  );
}
