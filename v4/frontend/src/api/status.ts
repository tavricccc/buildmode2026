import { client } from "./client";
import type { StatusSnapshot } from "../types/api";

export const status = {
  snapshot: () => client.get<StatusSnapshot>("/api/status"),
};

export const setup = {
  status: () => client.get<{ python: string; ffmpeg: boolean; sqlite: string }>("/api/setup/status"),
  prerequisites: () => client.get<{ items: Array<{ name: string; ok: boolean; detail: string }> }>("/api/setup/prerequisites"),
};
