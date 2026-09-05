import { useEffect, useState } from "react";
import { client } from "../api/client";
import { Card } from "../components/Card";

interface Snapshot { subject_id: string; snapshot: Record<string, unknown> }

export function HealthPanel() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  useEffect(() => {
    client.get<Snapshot>("/api/health/current").then(setSnap).catch(() => setSnap(null));
  }, []);
  return (
    <Card title="Health">
      {snap ? <pre>{JSON.stringify(snap.snapshot, null, 2)}</pre> : <p>無資料</p>}
    </Card>
  );
}
