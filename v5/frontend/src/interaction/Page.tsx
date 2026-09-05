import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { Badge, Card, Empty, ErrorBanner, errorText } from "../components/ui";
import type { AgentRun, InteractionMessage, MemoryRecord } from "../types/api";

const QUICK_PROMPTS = [
  "阿公早安！今天精神好嗎？",
  "我剛才頭有點暈，想先坐著休息一下",
  "我剛剛喝了一大杯溫開水",
  "今天下午天氣真好，想去戶外庭院走走散步",
  "今天中午胃口不太好，沒吃幾口飯",
  "我想問一下今天社工或護理師什麼時候會來？",
];

export function InteractionPage() {
  const [messages, setMessages] = useState<InteractionMessage[]>([]);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  };

  const load = useCallback(async () => {
    try {
      const [messageData, memoryData, runData] = await Promise.all([
        api.interactionMessages(),
        api.memories(100),
        api.agentRuns(100),
      ]);
      setMessages(messageData.messages);
      setMemories(memoryData.memories);
      setRuns(runData.runs);
      setError(null);
    } catch (exc) {
      setError(errorText(exc));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, busy]);

  const sendText = async (contentToSend: string) => {
    const trimmed = contentToSend.trim();
    if (!trimmed) return;
    setBusy(true);
    setNotice(null);
    try {
      await api.interactionTurn(trimmed);
      setText("");
      setNotice("已完成本輪溫暖同理互動，回覆已即時生成並寫入對話紀錄。");
      await load();
    } catch (exc) {
      setError(errorText(exc));
    } finally {
      setBusy(false);
    }
  };

  const understand = async () => {
    setBusy(true);
    setNotice(null);
    try {
      await api.interactionUnderstanding();
      setNotice("理解／動機驅動已完成，照護提案已寫入 agent run。");
      await load();
    } catch (exc) {
      setError(errorText(exc));
    } finally {
      setBusy(false);
    }
  };

  const decideMemory = async (id: string, status: "confirmed" | "invalidated") => {
    setBusy(true);
    try {
      await api.setMemoryStatus(id, status);
      await load();
    } catch (exc) {
      setError(errorText(exc));
    } finally {
      setBusy(false);
    }
  };

  const insights = runs.filter((run) => run.agent_name === "resident_understanding").slice(0, 3);
  const pending = memories.filter((memory) => memory.status === "pending");

  return (
    <div className="page-stack">
      <header className="page-heading">
        <div>
          <span className="eyebrow">ONE AGENT · TWO DRIVERS</span>
          <h1>住民互動與生活溝通</h1>
          <p>支援以同理、溫暖台灣在地口吻與長輩自然溝通；支援常見生活對話捷徑、動態語意生成與待確認照護記憶萃取。</p>
        </div>
      </header>

      {error && <ErrorBanner>{error}</ErrorBanner>}

      <div className="interaction-grid">
        <Card title="生活對話互動" aside={<Badge tone="ok">自然雙向對話 · 台灣在地語意</Badge>}>
          {/* 快捷對話氣泡 */}
          <div style={{ marginBottom: "12px" }}>
            <span style={{ fontSize: "0.85rem", color: "var(--muted)", display: "block", marginBottom: "6px" }}>
              💡 常見生活情境快捷傳送：
            </span>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
              {QUICK_PROMPTS.map((prompt, idx) => (
                <button
                  key={idx}
                  className="action ghost"
                  style={{ fontSize: "0.8rem", padding: "4px 8px", borderRadius: "14px" }}
                  disabled={busy}
                  onClick={() => void sendText(prompt)}
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>

          <div className="interaction-messages">
            {messages.length ? (
              messages.slice(-40).map((message) => (
                <article className={`interaction-message ${message.role}`} key={message.message_id}>
                  <small>
                    {message.role === "user" ? "👤 住民" : "🤖 長照照護助理"} · {message.intent || "生活互動"}
                  </small>
                  <p>{message.text}</p>
                </article>
              ))
            ) : (
              <Empty>尚無互動。可點擊上方生活捷徑或於下方輸入文字開始交流。</Empty>
            )}

            {busy && (
              <article className="interaction-message assistant" style={{ opacity: 0.85, borderLeft: "3px solid #f59e0b" }}>
                <small>🤖 長照照護助理 · 思考與生成中…</small>
                <p style={{ fontStyle: "italic", color: "var(--muted)" }}>正在同理長輩當前需求並生成溫暖回覆，請稍候…</p>
              </article>
            )}
            <div ref={messagesEndRef} />
          </div>

          <textarea
            value={text}
            disabled={busy}
            onChange={(event) => setText(event.target.value)}
            placeholder="對住民長輩說話或代表長輩輸入訊息；Enter 傳送，Shift+Enter 換行"
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void sendText(text);
              }
            }}
          />

          <div className="button-row" style={{ marginTop: "8px" }}>
            <button
              className="action primary"
              disabled={busy || !text.trim()}
              onClick={() => void sendText(text)}
            >
              {busy ? "處理中…" : "送出對話"}
            </button>
            <button className="action" disabled={busy} onClick={() => void understand()}>
              執行理解層（萃取動機與記憶）
            </button>
          </div>

          {notice && <p className="banner" style={{ marginTop: "10px" }}>{notice}</p>}
        </Card>

        <div className="side-stack">
          <Card title="理解／動機提案" aside={<Badge tone="muted">advisory</Badge>}>
            {insights.length ? (
              insights.map((run) => (
                <div className="audit-entry" key={run.agent_run_id}>
                  <small>{run.created_at}</small>
                  <pre>{JSON.stringify(run.output, null, 2)}</pre>
                </div>
              ))
            ) : (
              <Empty>尚未產生提案。點擊「執行理解層」可觸發動機模型推論。</Empty>
            )}
          </Card>

          <Card title="待確認照護記憶" aside={<Badge tone={pending.length ? "warn" : "muted"}>{pending.length}</Badge>}>
            {pending.length ? (
              pending.map((memory) => (
                <div className="memory-card" key={memory.memory_id}>
                  <strong>{memory.title}</strong>
                  <p>{memory.content}</p>
                  <small>信心 {Math.round(memory.confidence * 100)}% · {memory.memory_type}</small>
                  <div className="button-row" style={{ marginTop: "6px" }}>
                    <button className="action" disabled={busy} onClick={() => void decideMemory(memory.memory_id, "confirmed")}>
                      確認納入記憶
                    </button>
                    <button className="action ghost" disabled={busy} onClick={() => void decideMemory(memory.memory_id, "invalidated")}>
                      不採用
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <Empty>目前沒有待確認記憶。</Empty>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

