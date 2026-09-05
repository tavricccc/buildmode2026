import { useState } from "react";
import { Button } from "../components/Button";
import { settings } from "../api/settings";

interface Props {
  baseVersion: string | null;
  patch: Record<string, unknown>;
  onApplied: () => void | Promise<void>;
}

export function ApplyBar({ baseVersion, patch, onApplied }: Props) {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<string>("");
  return (
    <div className="apply-bar">
      <Button
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            const draft = await settings.draft(patch, baseVersion);
            if (draft.requires_confirmation) {
              const ok = window.confirm("此變更需要二次確認。是否繼續？");
              if (!ok) { setBusy(false); return; }
              const applied = await settings.apply(draft.draft_id, baseVersion ?? "", true);
              setFeedback(JSON.stringify(applied));
            } else {
              const applied = await settings.apply(draft.draft_id, baseVersion ?? "");
              setFeedback(JSON.stringify(applied));
            }
            await onApplied();
          } catch (e) {
            setFeedback(`error: ${(e as Error).message}`);
          } finally {
            setBusy(false);
          }
        }}
      >
        Draft / Apply
      </Button>
      {feedback ? <pre>{feedback}</pre> : null}
    </div>
  );
}
