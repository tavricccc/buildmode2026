import { useEffect, useState } from "react";
import { client } from "../api/client";
import { Button } from "../components/Button";

interface Props {
  name: string;
}

interface SecretMeta {
  configured: boolean;
  updated_at: string;
  fingerprint_suffix: string;
}

export function SecretInput({ name }: Props) {
  const [meta, setMeta] = useState<SecretMeta | null>(null);
  const [value, setValue] = useState("");

  async function refresh() {
    const r = await client.get<SecretMeta>(`/api/secrets/${name}`);
    setMeta(r);
  }
  useEffect(() => { refresh(); }, [name]);

  return (
    <div className="secret-input">
      {meta ? (
        <p>
          configured: <strong>{meta.configured ? "yes" : "no"}</strong> ·{" "}
          fingerprint: <code>****{meta.fingerprint_suffix}</code> ·{" "}
          updated: {meta.updated_at || "—"}
        </p>
      ) : <p>讀取中…</p>}
      <div>
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="新值（覆寫）"
        />
        <Button
          disabled={!value}
          onClick={async () => {
            await client.put(`/api/secrets/${name}`, { name, value });
            setValue("");
            await refresh();
          }}
        >
          覆寫
        </Button>
        <Button
          variant="danger"
          onClick={async () => {
            if (!window.confirm(`確定清除 ${name}？`)) return;
            await client.delete(`/api/secrets/${name}`);
            await refresh();
          }}
        >
          清除
        </Button>
      </div>
    </div>
  );
}
