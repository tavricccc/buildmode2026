import type { WsMessage } from "../types/api";

type Listener = (message: WsMessage) => void;

/**
 * WebSocket with reconnect and a REST-resync signal.
 *
 * The backend drops a client that cannot keep up rather than buffering
 * it, so a reconnect may have missed messages. `onResync` fires on every
 * (re)connection so the page refetches its state instead of trusting an
 * incremental stream it may have holes in.
 */
export class RealtimeClient {
  private socket: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private resyncers = new Set<() => void>();
  private backoffMs = 500;
  private closed = false;
  private timer: number | null = null;

  connect(): void {
    if (this.closed) return;
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${location.host}/ws`);
    this.socket = socket;

    socket.onopen = () => {
      this.backoffMs = 500;
      this.resyncers.forEach((fn) => fn());
    };
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data as string) as WsMessage;
        this.listeners.forEach((fn) => fn(message));
      } catch {
        /* a malformed frame is not worth tearing the connection down for */
      }
    };
    socket.onclose = () => this.scheduleReconnect();
    socket.onerror = () => socket.close();
  }

  private scheduleReconnect(): void {
    if (this.closed || this.timer !== null) return;
    this.timer = window.setTimeout(() => {
      this.timer = null;
      this.connect();
    }, this.backoffMs);
    this.backoffMs = Math.min(this.backoffMs * 2, 15_000);
  }

  onMessage(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  onResync(listener: () => void): () => void {
    this.resyncers.add(listener);
    return () => this.resyncers.delete(listener);
  }

  close(): void {
    this.closed = true;
    if (this.timer !== null) window.clearTimeout(this.timer);
    this.socket?.close();
  }
}
