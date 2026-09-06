import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { Badge, Card, Empty, ErrorBanner, errorText } from "../components/ui";
import type { AuditPayload } from "../types/api";

export function AuditPage() {
  const [data, setData] = useState<AuditPayload | null>(null);
  const [files, setFiles] = useState<Array<{ name: string; size_bytes: number; modified_at_ms: number }>>([]);
  const [tail, setTail] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { const [audit, logFiles] = await Promise.all([api.audit(500), api.auditLogFiles()]); setData(audit); setFiles(logFiles.files); setError(null); }
    catch (exc) { setError(errorText(exc)); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const openLog = async (name: string) => { try { setTail((await api.auditLogFile(name)).tail); } catch (exc) { setError(errorText(exc)); } };
  return <div className="page-stack">
    <header className="page-heading"><div><span className="eyebrow">READ-ONLY · REDACTED</span><h1>稽核後台</h1><p>顯示已保存的後端紀錄、資料庫統計、模型結構化輸出與 agent run；不保存或顯示隱藏推理。</p></div><button className="action" onClick={() => void load()}>重新整理</button></header>
    {error && <ErrorBanner>{error}</ErrorBanner>}
    {!data ? <Empty>載入中…</Empty> : <>
      <Card title="資料庫"><p className="mono">{data.database.path}</p><div className="audit-counts">{Object.entries(data.database.tables).map(([name, count]) => <span key={name}><b>{count}</b>{name}</span>)}</div></Card>
      <div className="interaction-grid"><Card title="後端 log 檔"><div className="record-list">{files.map((file) => <button className="audit-file" key={file.name} onClick={() => void openLog(file.name)}>{file.name}<small>{Math.round(file.size_bytes / 1024)} KB</small></button>)}</div>{tail && <pre className="log-tail">{tail}</pre>}</Card><Card title="App logs"><div className="record-list">{data.logs.map((log) => <article className="audit-entry" key={log.log_id}><Badge tone={log.level === "error" ? "bad" : log.level === "warn" ? "warn" : "muted"}>{log.level}</Badge><strong>{log.source}</strong><small>{log.created_at}</small><p>{log.message}</p></article>)}</div></Card></div>
      <Card title="L2 結構化觀察"><div className="record-list">{data.observations.length ? data.observations.map((item) => <article className="audit-entry" key={item.observation_id}><small>{new Date(item.observed_at_ms).toLocaleString()} · 信心 {Math.round(item.confidence * 100)}%</small><p>{item.summary}</p><pre>{JSON.stringify(item.payload, null, 2)}</pre></article>) : <Empty>尚無有效 observation。</Empty>}</div></Card>
      <Card title="模型輸出與錯誤"><div className="record-list">{data.model_calls.map((call, index) => <article className="audit-entry" key={String(call.call_id ?? index)}><Badge tone={call.status === "failed" || call.status === "invalid" ? "bad" : "ok"}>{String(call.status)}</Badge><strong>{String(call.layer)} · {String(call.model)}</strong><small>{String(call.created_at)} · {String(call.latency_ms)} ms</small><p>{String(call.error_code ?? "")}: {String(call.error_message ?? "")}</p><pre>{String(call.response_text ?? "")}</pre></article>)}</div></Card>
      <Card title="Agent runs"><div className="record-list">{data.agent_runs.map((run) => <article className="audit-entry" key={run.agent_run_id}><strong>{run.agent_name}</strong><small>{run.status} · {run.created_at}</small><pre>{JSON.stringify(run.output, null, 2)}</pre></article>)}</div></Card>
    </>}
  </div>;
}
