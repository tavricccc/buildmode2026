import { useEffect, useState } from "react";
import { client } from "../api/client";
import { Card } from "../components/Card";

interface Summary {
  confirmed_sessions: number;
  estimated_total_ml: number;
  target_ml: number;
  completion_ratio: number;
}

export function HydrationPanel() {
  const [s, setS] = useState<Summary | null>(null);
  useEffect(() => {
    client.get<Summary>("/api/hydration/summary").then(setS).catch(() => setS(null));
  }, []);
  return (
    <Card title="Hydration">
      {s ? (
        <>
          <p>本次 session: {s.confirmed_sessions}</p>
          <p>估算量: {s.estimated_total_ml} / {s.target_ml} ml</p>
          <p>完成率: {(s.completion_ratio * 100).toFixed(0)}%</p>
        </>
      ) : <p>無資料</p>}
    </Card>
  );
}
