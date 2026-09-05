import { Card } from "../components/Card";
import type { WSMessage } from "../types/ws";

interface Props {
  lastMessage: WSMessage | null;
}

export function LogPanel({ lastMessage }: Props) {
  return (
    <Card title="Log">
      {lastMessage ? (
        <pre>{JSON.stringify({ type: lastMessage.type, occurred_at: lastMessage.occurred_at, payload: lastMessage.payload }, null, 2)}</pre>
      ) : <p>等待訊息…</p>}
    </Card>
  );
}
