import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { Badge, Card, Empty, ErrorBanner, errorText } from "../components/ui";
import type { SettingsPayload } from "../types/api";
import { SecretInput } from "./SecretInput";

const SLOT_ROLE: Record<"l2" | "l3", string> = {
  l2: "常態語意觀察",
  l3: "升級深度判讀",
};

const GROUPS: { key: keyof SettingsPayload["policy"]; label: string; hint: string }[] = [
  { key: "l1", label: "L1 Person Gate", hint: "只負責在場判斷；進入與離開需要不同數量的連續觀察。" },
  { key: "cadence", label: "分析頻率", hint: "控制各層執行頻率；Heartbeat 讓空房跳過後仍保留稀疏安全檢查。" },
  { key: "fall", label: "跌倒判定", hint: "多次一致的觀察才會把 suspect 提升為 confirmed。" },
  { key: "hydration", label: "飲水判定", hint: "Cooldown 可避免 Replay 或重複片段重複計算。" },
  { key: "escalation", label: "L3 升級", hint: "定義何時使用 MiniMax，以及避免迴圈耗盡預算的上限。" },
  { key: "notification", label: "通知政策", hint: "只有這裡可設定頻道與收件者；模型無法變更。" },
];

export function SettingsPage() {
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [draft, setDraft] = useState<SettingsPayload["policy"] | null>(null);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.settings();
      setSettings(data);
      setDraft(structuredClone(data.policy));
      setLoadError(null);
    } catch (exc) {
      setLoadError(errorText(exc));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  // Without this the page sat on "載入中…" for ever whenever the backend was
  // unreachable, which reads as "still working" rather than "it failed".
  if (loadError) return <Card title="系統設定"><ErrorBanner>無法讀取設定：{loadError}</ErrorBanner></Card>;
  if (!settings || !draft) return <Card title="系統設定"><Empty>載入中…</Empty></Card>;

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
      setMessage(`已套用為 ${result.version}。`);
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
    setMessage(null);
    // A rollback that fails silently leaves the caregiver believing a
    // different policy version is live than the one actually running.
    try { await api.rollback(version); setMessage(`已回滾至 ${version}。`); await load(); }
    catch (exc) { setMessage(`回滾失敗：${errorText(exc)}`); }
    finally { setBusy(false); }
  };

  // A provider change makes the backend rebuild both layers and restart the
  // cascade, so it holds `busy`: the switch takes a moment, and two of them
  // in flight at once would race the rebuild.
  const saveProvider = async (slot: "l2" | "l3", patch: Record<string, string>) => {
    setBusy(true);
    setMessage(null);
    try {
      await api.saveProviders({ [slot]: patch });
      await load();
    } catch (exc) {
      setMessage(`Provider 設定未儲存：${errorText(exc)}`);
    } finally { setBusy(false); }
  };

  return (
    <div className="stack">
      <header className="page-heading"><div><span className="eyebrow">Policy & Providers</span><h1>系統設定</h1><p>模型、Secrets 與 Policy 版本均可稽核；只有 Policy 能授權通知。</p></div></header>
      <Card title="Secrets" aside={<span className="muted" style={{ fontSize: 12 }}>僅可寫入，API 永不回傳原值</span>}>
        <SecretInput label="本機 vLLM API Key（選填）" secretKey="VLLM_API_KEY"
                     state={settings.secrets["VLLM_API_KEY"]} onSaved={load} />
        <SecretInput label="Gemini API Key（L2）" secretKey="GEMINI_API_KEY"
                     state={settings.secrets["GEMINI_API_KEY"]} onSaved={load} />
        <SecretInput label="MiniMax API Key（L3）" secretKey="MINIMAX_API_KEY"
                     state={settings.secrets["MINIMAX_API_KEY"]} onSaved={load} />
        <SecretInput label="RTSP 密碼" secretKey="RTSP_PASSWORD"
                     state={settings.secrets["RTSP_PASSWORD"]} onSaved={load} />
        <SecretInput label="Telegram Bot Token" secretKey="TELEGRAM_BOT_TOKEN"
                     state={settings.secrets["TELEGRAM_BOT_TOKEN"]} onSaved={load} />
      </Card>

      <Card title="模型槽" aside={<span className="muted" style={{ fontSize: 12 }}>L2 與 L3 分別設定</span>}>
        <div className="grid cols-2">
          {(["l2", "l3"] as const).map((slot) => {
            const provider = settings.providers[slot];
            const options = settings.provider_options[slot];
            const active = options.find((option) => option.name === provider.name);
            const local = provider.name === "local_vllm";
            return (
              <div key={slot}>
                <h2 style={{ marginBottom: ".5rem" }}>
                  {slot.toUpperCase()} · {SLOT_ROLE[slot]}
                </h2>

                <div className="segmented compact" role="group" aria-label={`${slot.toUpperCase()} 服務供應商`}>
                  {options.map((option) => (
                    <button key={option.name} aria-selected={option.name === provider.name}
                            disabled={busy}
                            onClick={() => void saveProvider(slot, { name: option.name })}>
                      {option.label}
                    </button>
                  ))}
                </div>

                {/* Switching a slot replaces its base URL, API style and secret
                    key with that provider's defaults, so these two inputs are
                    remounted on the provider name — a stale defaultValue would
                    otherwise keep showing the previous provider's model. */}
                <label className="field" style={{ marginTop: 12 }}><span>模型名稱</span>
                  <input key={`${slot}-model-${provider.name}`}
                         defaultValue={provider.model}
                         placeholder={active?.default_model}
                         spellCheck={false}
                         onBlur={(event) => void saveProvider(slot, { model: event.target.value })} />
                </label>
                <label className="field"><span>Base URL</span>
                  <input key={`${slot}-url-${provider.name}`}
                         defaultValue={provider.base_url}
                         spellCheck={false}
                         onBlur={(event) => void saveProvider(slot, { base_url: event.target.value })} />
                </label>

                <Badge tone={provider.key_configured || local ? "ok" : "warn"}>
                  {local ? "本機端點，不需要 API Key"
                    : provider.key_configured ? "已設定 API Key"
                    : `未設定 ${active?.secret_key ?? "API Key"}，使用 offline stub`}
                </Badge>
              </div>
            );
          })}
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

      <Card title="套用新版本">
        <div className="row">
          <input placeholder="說明改了什麼，以及原因" value={note}
                 onChange={(event) => setNote(event.target.value)} style={{ flex: 1 }} />
          <button className="action primary" disabled={!dirty || busy} onClick={() => void apply()}>
            {dirty ? "建立並套用新版本" : "沒有變更"}
          </button>
        </div>
        {message && <p className="banner" style={{ marginTop: ".7rem" }}>{message}</p>}
        <h2 style={{ marginTop: "1.1rem" }}>版本紀錄</h2>
        <table>
          <thead><tr><th>版本</th><th>說明</th><th>建立時間</th><th /></tr></thead>
          <tbody>
            {settings.versions.map((version) => (
              <tr key={version.version}>
                <td className="mono">{version.version} {version.is_active ? <Badge tone="ok">active</Badge> : null}</td>
                <td className="muted">{version.note || "—"}</td>
                <td className="mono muted">{version.created_at.slice(0, 19).replace("T", " ")}</td>
                <td>
                  {!version.is_active && (
                    <button className="action" disabled={busy}
                            onClick={() => void rollback(version.version)}>回滾</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="主機管理項目" aside={<span className="muted" style={{ fontSize: 12 }}>無法從瀏覽器修改</span>}>
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
