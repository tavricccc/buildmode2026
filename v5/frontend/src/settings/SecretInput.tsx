import { useState } from "react";
import { api } from "../api/client";
import { Badge } from "../components/ui";

/**
 * Write-only secret field (v5 03 §Setup/Settings).
 *
 * The backend never returns a stored secret, so this component has
 * nothing to prefill with and does not pretend otherwise: it shows
 * whether a key is configured and where it came from, and offers to
 * replace it. There is no "reveal" affordance because there is nothing
 * on this side to reveal.
 */
export function SecretInput({ label, secretKey, state, onSaved }: {
  label: string;
  secretKey: string;
  state: { configured: boolean; source: string; length: number } | undefined;
  onSaved: () => void;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const save = async (next: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await api.saveSecret(secretKey, next);
      setValue("");
      setMessage(next ? "Saved." : "Cleared.");
      onSaved();
    } catch (exc) {
      setMessage((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <label className="field">
      <span>
        {label}{" "}
        {state?.configured
          ? <Badge tone="ok">configured · {state.source} · {state.length} chars</Badge>
          : <Badge tone="warn">not set</Badge>}
      </span>
      <div className="row">
        <input
          type="password"
          value={value}
          autoComplete="off"
          placeholder={state?.configured ? "replace the stored value" : "paste the key"}
          onChange={(event) => setValue(event.target.value)}
          style={{ flex: 1 }}
        />
        <button className="action" disabled={busy || !value} onClick={() => void save(value)}>Save</button>
        {state?.configured && state.source === "store" && (
          <button className="action" disabled={busy} onClick={() => void save("")}>Clear</button>
        )}
      </div>
      {message && <span className="muted" style={{ fontSize: 12 }}>{message}</span>}
    </label>
  );
}
