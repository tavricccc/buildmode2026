import { client } from "./client";
import type { ModelEndpoint, InstalledModel, DeploymentType } from "../types/api";

export const modelEndpoints = {
  list: () => client.get<{ endpoints: ModelEndpoint[] }>("/api/model-endpoints"),
  upsert: (body: { id: string; display_name: string; deployment_type: DeploymentType; base_url: string; adapter_mode: string }) =>
    client.post<{ id: string; ok: boolean }>("/api/model-endpoints", body),
  test: (id: string) => client.post<{ ok: boolean; models?: string[]; code?: string; detail?: string }>(`/api/model-endpoints/${id}/test`),
  listModels: (id: string) => client.get<{ models: string[] }>(`/api/model-endpoints/${id}/models`),
  remove: (id: string) => client.delete<{ ok: boolean }>(`/api/model-endpoints/${id}`),
};

export const installedModels = {
  list: () => client.get<{ installed: InstalledModel[] }>("/api/models/installed"),
  install: (body: { endpoint_id: string; capability: string; remote_model_id: string; display_name: string; source_type: string; catalog_id?: string }) =>
    client.post<{ job_id: string }>("/api/models/install", body),
  probe: (model_id: string, body: { endpoint_id: string; capability: string; remote_model_id: string }) =>
    client.post<{ ok: boolean; detail: string }>(`/api/models/${model_id}/probe`, body),
  activate: (model_id: string) => client.post<{ ok: boolean; model_id: string }>(`/api/models/${model_id}/activate`),
};

export const catalog = {
  list: () => client.get<{ models: Array<{ id: string; display_name: string; capability: string }> }>("/api/models/catalog"),
};
