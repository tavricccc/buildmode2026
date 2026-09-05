import { useState } from "react";
import { Button } from "./Button";

interface ConfirmDialogProps {
  title: string;
  body: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({ title, body, confirmLabel = "確認", onConfirm, onCancel }: ConfirmDialogProps) {
  const [busy, setBusy] = useState(false);
  return (
    <div className="dialog-backdrop">
      <div className="dialog">
        <h2>{title}</h2>
        <p>{body}</p>
        <div className="dialog-actions">
          <Button variant="secondary" onClick={onCancel}>取消</Button>
          <Button
            variant="danger"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
              } finally {
                setBusy(false);
              }
            }}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
