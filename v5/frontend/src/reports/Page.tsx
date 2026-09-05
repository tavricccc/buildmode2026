import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { Badge, Card, Empty, ErrorBanner, errorText } from "../components/ui";
import type { SocialWorkRecord, StatusReport } from "../types/api";

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
      const result = await api.autoGenerateSocialWorkRecord(autoHours, "case_note", autoAuthor);
      setAutoNotice(
        `✅ 已成功讀取並彙整過去 ${autoHours} 小時照護資料！產生標準 SOAP 社工日誌（涵蓋事件 ${result.stats.events_count} 筆、跌倒通報 ${result.stats.falls_count} 件、補水紀錄 ${result.stats.hydration_events_count} 次、結構觀察 ${result.stats.observations_count} 筆）。已同步歸檔至社工紀錄與狀態報告。`
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
          <p>支援讀取系統事件與照護日誌自動產出標準 SOAP 臨床日誌，引用已儲存之事件、感測及生活紀錄；初稿需由專業人員覆核。</p>
        </div>
      </header>

      {error && <ErrorBanner>{error}</ErrorBanner>}

      {/* 核心功能：讀取事件自動產生社工日誌 */}
      <Card
        title="⚡ 讀取系統事件 · 自動產生社工日誌"
        aside={<Badge tone="ok">標準 SOAP 照護架構</Badge>}
      >
        <p style={{ margin: "0 0 14px 0", color: "var(--muted)", fontSize: "0.95rem", lineHeight: 1.6 }}>
          自動讀取指定時間區間內之<b>系統安全事件（跌倒通報、離床警報）</b>、<b>水分攝取與飲食日誌</b>、<b>環境影像感知（L2/L3 行為觀察）</b>、<b>生理量測數值</b>及<b>住民互動主訴</b>，自動彙整為符合專業長照稽核規範的 SOAP 社工照護日誌並直接存檔。
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
            {busy ? "讀取事件與彙整中…" : "⚡ 立即讀取事件並自動產生社工日誌"}
          </button>
        </div>

        {autoNotice && <p className="banner" style={{ marginTop: "12px", background: "rgba(16, 185, 129, 0.15)", border: "1px solid rgba(16, 185, 129, 0.4)", color: "#10b981", padding: "10px 14px", borderRadius: "6px" }}>{autoNotice}</p>}
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
            <textarea value={content} onChange={(event) => setContent(event.target.value)} placeholder="只填已實際訪視、聯繫或確認的事項。" />
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
                  <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: "8px 0", fontSize: "0.95rem" }}>{record.content}</pre>
                  <small style={{ color: "var(--muted)" }}>標籤：{record.tags.join(" · ") || "無"}</small>
                </article>
              );
            })
          ) : (
            <Empty>尚無符合條件之社工紀錄。點擊上方「立即讀取事件並自動產生社工日誌」即可一鍵生成。</Empty>
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
                <small>來源：社工 {report.sources.social_work_record_ids?.length ?? 0} 筆、事件 {report.sources.event_ids?.length ?? 0} 筆、觀察 {report.sources.observation_ids?.length ?? 0} 筆</small>
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

