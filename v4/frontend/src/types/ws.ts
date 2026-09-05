export type WSMessageType =
  | "system.status"
  | "video.progress"
  | "health.updated"
  | "audio.vad"
  | "audio.transcript"
  | "camera.status"
  | "vision.loop.tick"
  | "vision.loop.dropped"
  | "event.created"
  | "event.updated"
  | "local_analysis.started"
  | "local_analysis.completed"
  | "cloud_analysis.started"
  | "cloud_analysis.completed"
  | "action.triggered"
  | "tool.called"
  | "observer.finding"
  | "notification.updated"
  | "setup.updated"
  | "model.download.progress"
  | "model.activated"
  | "log.appended"
  | "model.install.progress"
  | "model.probe.completed"
  | "endpoint.updated"
  | "settings.applied"
  | "settings.rollback.completed";

export interface WSMessage {
  message_id: string;
  type: WSMessageType;
  occurred_at: string;
  correlation_id?: string;
  schema_version: string;
  payload: Record<string, unknown>;
}
