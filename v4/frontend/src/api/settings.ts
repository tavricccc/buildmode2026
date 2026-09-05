import { client } from "./client";
import type { SettingsBundle, ConfigVersion } from "../types/api";

export const settings = {
  schema: () => client.get<{ categories: { ui_editable: string[]; secret_write_only: string[]; host_managed: string[] }; defaults: SettingsBundle }>("/api/settings/schema"),
  getActive: () => client.get<{ version_id: string | null; settings: SettingsBundle }>("/api/settings"),
  draft: (patch: Record<string, unknown>, base_version: string | null) =>
    client.post<{ draft_id: string; requires_confirmation: boolean; restart_required: boolean; preview: SettingsBundle; validation_errors: string[] }>(
      "/api/settings/draft",
      { patch, base_version },
    ),
  test: (draft_id: string) => client.post<{ ok: boolean; failures: string[] }>(`/api/settings/test?draft_id=${draft_id}`),
  apply: (draft_id: string, base_version: string, confirm = false) =>
    client.post<{ status: string; version_id: string; restart_required: boolean }>("/api/settings/apply", { draft_id, base_version, confirm }),
  versions: () => client.get<{ versions: ConfigVersion[] }>("/api/settings/versions"),
  rollback: (id: string) => client.post<{ version_id: string; rolled_back_from: string }>(`/api/settings/rollback/${id}`),
};
