import type { SettingsBundle } from "../types/api";

interface Props {
  value: SettingsBundle;
  onChange: (patch: Record<string, unknown>) => void;
}

export function DraftEditor({ value, onChange }: Props) {
  return (
    <div className="draft-editor">
      <label>
        <span>fall.min_confidence</span>
        <input
          type="number"
          step="0.05"
          min={0}
          max={1}
          value={value.fall.min_confidence}
          onChange={(e) => onChange({ fall: { min_confidence: Number(e.target.value) } })}
        />
      </label>
      <label>
        <span>hydration.target_ml_per_day</span>
        <input
          type="number"
          value={value.hydration.target_ml_per_day}
          onChange={(e) => onChange({ hydration: { target_ml_per_day: Number(e.target.value) } })}
        />
      </label>
      <label>
        <span>vision_loop.interval_ms</span>
        <input
          type="number"
          value={value.vision_loop.interval_ms}
          onChange={(e) => onChange({ vision_loop: { interval_ms: Number(e.target.value) } })}
        />
      </label>
      <label>
        <span>notification.allowed_chat_ids (逗號分隔)</span>
        <input
          value={value.notification.allowed_chat_ids.join(",")}
          onChange={(e) => onChange({ notification: { allowed_chat_ids: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) } })}
        />
      </label>
    </div>
  );
}
