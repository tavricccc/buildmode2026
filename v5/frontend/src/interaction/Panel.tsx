import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Badge, Card, Empty } from "../components/ui";

type Message = { message_id: string; role: string; text: string; intent: string };
type Memory = { memory_id: string; title: string; content: string; status: string; confidence: number };

export function InteractionPanel() {
  const [text, setText] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    void api.interactionMessages().then((data) => setMessages(data.messages)).catch(() => undefined);
    void api.memories("pending").then((data) => setMemories(data.memories)).catch(() => undefined);
  };
  useEffect(refresh, []);

  const send = async () => {
    if (!text.trim() || busy) return;
    setBusy(true); setError(null);
    try { await api.interactionTurn(text.trim()); setText(""); refresh(); }
    catch (exc) { setError((exc as Error).message); }
    finally { setBusy(false); }
  };

  const confirm = async (memoryId: string) => {
    await api.memoryStatus(memoryId, "confirmed");
    refresh();
  };

  return (
    <Card title="Resident interaction & memory">
      <div className="stack">
        <div className="scroll" style={{ maxHeight: "14rem" }}>
          {messages.length === 0 ? <Empty>No conversation yet.</Empty> : messages.map((message) => (
            <div key={message.message_id} style={{ marginBottom: ".45rem" }}>
              <Badge tone={message.role === "assistant" ? "ok" : "muted"}>{message.role}</Badge>{" "}
              <span>{message.text}</span>
            </div>
          ))}
        </div>
        <div className="row">
          <input value={text} onChange={(event) => setText(event.target.value)}
                 onKeyDown={(event) => { if (event.key === "Enter") void send(); }}
                 placeholder="輸入住民訊息…" aria-label="Resident message" />
          <button className="action primary" onClick={() => void send()} disabled={busy || !text.trim()}>Send</button>
        </div>
        {error && <p className="banner bad" style={{ margin: 0 }}>{error}</p>}
        {memories.length > 0 && <div>
          <div className="muted" style={{ fontSize: 12, marginBottom: ".35rem" }}>Pending memory candidates — confirm before use</div>
          {memories.map((memory) => (
            <div key={memory.memory_id} className="row" style={{ justifyContent: "space-between", marginBottom: ".35rem" }}>
              <span><b>{memory.title}</b> · {memory.content}</span>
              <button className="action" onClick={() => void confirm(memory.memory_id)}>Confirm</button>
            </div>
          ))}
        </div>}
      </div>
    </Card>
  );
}
