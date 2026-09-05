export type Json = Record<string, any>;

export async function api<T = Json>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(init?.headers || {}) }, ...init });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body?.error?.message || body?.detail || `Request failed: ${response.status}`);
  return body as T;
}

export function wsUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws`;
}

export function mediaWsUrl(cameraId = "browser-camera", mediaType = "video/webm") {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/media?camera_id=${encodeURIComponent(cameraId)}&media_type=${encodeURIComponent(mediaType)}`;
}

export function formatDate(value?: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-TW", { hour12: false });
}

export function percent(value: number) { return `${Math.round(value * 100)}%`; }
