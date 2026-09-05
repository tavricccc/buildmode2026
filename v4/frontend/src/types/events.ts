export interface EventRecord {
  id: string;
  event_type: "fall" | "hydration";
  status: string;
  occurred_at: string;
  confidence: number;
  model_endpoint_id?: string;
  deployment_type?: "local" | "cloud";
  config_version?: string;
}
