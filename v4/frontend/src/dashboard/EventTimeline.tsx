import { useEffect, useState } from "react";
import { client } from "../api/client";
import { Card } from "../components/Card";

interface EventRec { id: string; event_type: string; status: string; occurred_at: string; confidence: number }

export function EventTimeline() {
  const [events, setEvents] = useState<EventRec[]>([]);
  useEffect(() => {
    client.get<{ events: EventRec[] }>("/api/events").then((r) => setEvents(r.events)).catch(() => setEvents([]));
  }, []);
  return (
    <Card title="Events">
      {events.length === 0 ? <p>無事件</p> : (
        <ul>
          {events.map((e) => (
            <li key={e.id}>{e.occurred_at} — {e.event_type} — {e.status} (conf {(e.confidence * 100).toFixed(0)}%)</li>
          ))}
        </ul>
      )}
    </Card>
  );
}
