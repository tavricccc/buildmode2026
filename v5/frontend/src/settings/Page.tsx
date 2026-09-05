import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { Badge, Card, Empty } from "../components/ui";
import type { SettingsPayload } from "../types/api";
import { SecretInput } from "./SecretInput";

const GROUPS: { key: keyof SettingsPayload["policy"]; label: string; hint: string }[] = [
  { key: "l1", label: "L1 person gate", hint: "Presence filtering only. Entering costs frames_to_enter readings, leaving costs frames_to_exit." },
  { key: "cadence", label: "Cadence", hint: "How often each layer may run. heartbeat_interval_sec is the sparse check that survives an L1 skip." },
  { key: "fall", label: "Fall", hint: "confirm_observations corroborating readings promote a suspect to confirmed." },
  { key: "hydration", label: "Hydration", hint: "session_cooldown_sec is what stops a replay from double-counting." },
  { key: "escalation", label: "L3 escalation", hint: "When MiniMax may be spent, and the ceilings that stop a stuck loop draining the budget." },
  { key: "notification", label: "Notification", hint: "The only place a channel or a recipient is named. No model can change these." },
];

export function SettingsPage() {
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [draft, setDraft] = useState<SettingsPayload["policy"] | null>(null);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const data = await api.settings();
    setSettings(data);
    setDraft(structuredClone(data.policy));
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (!settings || !draft) return <Card title="Settings"><Empty>Loading…</Empty></Card>;

  const dirty = JSON.stringify(draft) !== JSON.stringify(settings.policy);

  const setField = (group: string, field: string, raw: string) => {
    setDraft((current) => {
      if (!current) return current;
      const next = structuredClone(current);
      const bucket = next[group as keyof typeof next] as Record<string, unknown>;
      const existing = bucket[field];
      bucket[field] = typeof existing === "boolean" ? raw === "true"
        : typeof existing === "number" ? Number(raw)
        : raw;
      return next;
    });
  };

  const apply = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.saveSettings(draft, note || "edited in Settings");
      setMessage(`Applied as ${result.version}.`);
      setNote("");
      await load();
    } catch (exc) {
      setMessage((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const rollback = async (version: string) => {
    setBusy(true);
    try { await api.rollback(version); setMessage(`Rolled back to ${version}.`); await load(); }
    finally { setBusy(false); }
  };

  return (
    <div className="stack">
      <Card title="Secrets" aside={<span className="muted" style={{ fontSize: 12 }}>write-only — never returned by the API</span>}>
        <SecretInput label="Local vLLM API key (optional)" secretKey="VLLM_API_KEY"
                     state={settings.secrets["VLLM_API_KEY"]} onSaved={load} />
        <SecretInput label="Gemini API key (L2)" secretKey="GEMINI_API_KEY"
                     state={settings.secrets["GEMINI_API_KEY"]} onSaved={load} />
        <SecretInput label="MiniMax API key (L3)" secretKey="MINIMAX_API_KEY"
                     state={settings.secrets["MINIMAX_API_KEY"]} onSaved={load} />
        <SecretInput label="RTSP password" secretKey="RTSP_PASSWORD"
                     state={settings.secrets["RTSP_PASSWORD"]} onSaved={load} />
        <SecretInput label="Telegram bot token" secretKey="TELEGRAM_BOT_TOKEN"
                     state={settings.secrets["TELEGRAM_BOT_TOKEN"]} onSaved={load} />
      </Card>

      <Card title="Model slots" aside={<span className="muted" style={{ fontSize: 12 }}>configured independently by design</span>}>
        <div className="grid cols-2">
          {(["l2", "l3"] as const).map((slot) => (
            <div key={slot}>
              <h2 style={{ marginBottom: ".5rem" }}>{slot.toUpperCase()} · {settings.providers[slot].name}</h2>
              <label className="field"><span>Model</span>
                <input defaultValue={settings.providers[slot].model}
                       onBlur={(event) => void api.saveProviders({ [slot]: { model: event.target.value } }).then(load)} />
              </label>
              <label className="field"><span>Base URL</span>
                <input defaultValue={settings.providers[slot].base_url}
                       onBlur={(event) => void api.saveProviders({ [slot]: { base_url: event.target.value } }).then(load)} />
              </label>
              <Badge tone={settings.providers[slot].name === "local_vllm" || settings.providers[slot].key_configured ? "ok" : "warn"}>
                {settings.providers[slot].name === "local_vllm" ? "local vLLM endpoint" : settings.providers[slot].key_configured ? "key configured" : "no key — using the offline stub"}
              </Badge>
            </div>
          ))}
        </div>
      </Card>

      {GROUPS.map((group) => (
        <Card key={group.key as string} title={group.label}
              aside={<span className="muted" style={{ fontSize: 12 }}>{group.hint}</span>}>
          <div className="grid cols-3">
            {Object.entries(draft[group.key] as Record<string, unknown>).map(([field, value]) => (
              <label className="field" key={field}>
                <span>{field}</span>
                {typeof value === "boolean" ? (
                  <select value={String(value)} onChange={(e) => setField(group.key as string, field, e.target.value)}>
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                ) : field === "detector_id" ? (
                  <select value={String(value)} onChange={(e) => setField(group.key as string, field, e.target.value)}>
                    {Object.entries(settings.detectors).map(([id, description]) => (
                      <option key={id} value={id} title={description}>{id}</option>
                    ))}
                  </select>
                ) : Array.isArray(value) ? (
                  <input value={value.join(", ")} readOnly />
                ) : (
                  <input value={String(value)} onChange={(e) => setField(group.key as string, field, e.target.value)} />
                )}
              </label>
            ))}
          </div>
        </Card>
      ))}

      <Card title="Apply">
        <div className="row">
          <input placeholder="What changed, and why?" value={note}
                 onChange={(event) => setNote(event.target.value)} style={{ flex: 1 }} />
          <button className="action primary" disabled={!dirty || busy} onClick={() => void apply()}>
            {dirty ? "Apply as a new version" : "No changes"}
          </button>
        </div>
        {message && <p className="banner" style={{ marginTop: ".7rem" }}>{message}</p>}
        <h2 style={{ marginTop: "1.1rem" }}>Version history</h2>
        <table>
          <thead><tr><th>Version</th><th>Note</th><th>Created</th><th /></tr></thead>
          <tbody>
            {settings.versions.map((version) => (
              <tr key={version.version}>
                <td className="mono">{version.version} {version.is_active ? <Badge tone="ok">active</Badge> : null}</td>
                <td className="muted">{version.note || "—"}</td>
                <td className="mono muted">{version.created_at.slice(0, 19).replace("T", " ")}</td>
                <td>
                  {!version.is_active && (
                    <button className="action" disabled={busy}
                            onClick={() => void rollback(version.version)}>Roll back</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="Host-managed" aside={<span className="muted" style={{ fontSize: 12 }}>not editable from the browser (v5 03)</span>}>
        <table>
          <tbody>
            {Object.entries(settings.host_managed).map(([key, value]) => (
              <tr key={key}><td className="mono muted" style={{ width: "9rem" }}>{key}</td><td className="mono">{value}</td></tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
