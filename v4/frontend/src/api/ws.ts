import { useEffect, useRef, useState } from "react";
import type { WSMessage, WSMessageType } from "../types/ws";

export function useWebSocket(onMessage?: (msg: WSMessage) => void): { last: WSMessage | null; connected: boolean } {
  const [last, setLast] = useState<WSMessage | null>(null);
  const [connected, setConnected] = useState(false);
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;

  useEffect(() => {
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as WSMessage;
        setLast(msg);
        handlerRef.current?.(msg);
      } catch {
        // ignore non-JSON frames
      }
    };
    return () => ws.close();
  }, []);

  return { last, connected };
}

export function filterByType(messages: WSMessage[], type: WSMessageType): WSMessage[] {
  return messages.filter((m) => m.type === type);
}
