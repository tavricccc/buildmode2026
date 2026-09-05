import { useEffect, useState } from "react";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { DraftEditor } from "./DraftEditor";
import { ApplyBar } from "./ApplyBar";
import { SecretInput } from "./SecretInput";
import { settings } from "../api/settings";
import type { SettingsBundle, ConfigVersion } from "../types/api";

export default function SettingsPage() {
  const [active, setActive] = useState<{ version_id: string | null; settings: SettingsBundle } | null>(null);
  const [versions, setVersions] = useState<ConfigVersion[]>([]);
  const [draftPatch, setDraftPatch] = useState<Record<string, unknown>>({});

  async function refresh() {
    const r = await settings.getActive();
    setActive(r);
    const v = await settings.versions();
    setVersions(v.versions);
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="settings-page">
      <h2>Settings</h2>
      {active ? (
        <Card title={`Active: ${active.version_id ?? "—"}`}>
          <DraftEditor value={active.settings} onChange={setDraftPatch} />
          <ApplyBar
            baseVersion={active.version_id}
            patch={draftPatch}
            onApplied={refresh}
          />
        </Card>
      ) : (
        <p>讀取中…</p>
      )}
      <Card title="Telegram Bot token">
        <SecretInput name="telegram_bot_token" />
      </Card>
      <Card title="版本歷史">
        <ul>
          {versions.map((v) => (
            <li key={v.id}>
              {v.id} — {v.activated_at ?? "未啟用"} — {v.created_by}
            </li>
          ))}
        </ul>
        <Button onClick={async () => { if (versions[0]) { await settings.rollback(versions[0].id); await refresh(); } }}>
          Rollback 到第一個
        </Button>
      </Card>
    </div>
  );
}
