import { Badge, Card, Empty, clock } from "../components/ui";
import type { ObservationRecord } from "../types/api";

export function ObservationHistory({ observations }: { observations: ObservationRecord[] }) {
  return (
    <Card title="Recent VLM observations" aside="newest first · max 12">
      {observations.length === 0 ? <Empty>No accepted observations yet.</Empty> : (
        <div className="scroll">
          {observations.slice(0, 12).map((item) => {
            const fall = item.payload.fall;
            const hydration = item.payload.hydration;
            const signal = fall?.posture === "lying" && fall.near_floor ? "possible fall"
              : hydration?.drinking_motion ? "drinking" : item.payload.person_visible ? "person present" : "no person";
            return <div key={item.observation_id} style={{ borderTop: "1px solid var(--line)", padding: ".55rem 0" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span><span className="mono muted">{clock(item.observed_at_ms)}</span>{" "}<Badge tone={signal === "possible fall" ? "bad" : "muted"}>{signal}</Badge></span>
                <span className="mono muted">conf {item.confidence.toFixed(2)}</span>
              </div>
              <div style={{ marginTop: ".25rem" }}>{item.summary || item.payload.scene_summary || "—"}</div>
              <div className="mono muted" style={{ fontSize: 11, marginTop: ".2rem" }}>run {item.run_id}</div>
            </div>;
          })}
        </div>
      )}
    </Card>
  );
}
