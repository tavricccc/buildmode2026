import { Badge, Card, Stat, healthTone, ms } from "../components/ui";
import type { RunStats, Status } from "../types/api";

/**
 * The three-layer panel v5 03 asks for.
 *
 * It is laid out as three cards in cascade order because the number that
 * matters most is the relationship between them: L1 skips are only good
 * news if L1 is healthy, and L3 calls are only good news if they are rare.
 */
export function PipelinePanel({ status, stats }: { status: Status; stats: RunStats }) {
  const { l1, l2, l3 } = status.cascade;
  const windows = stats.windows || 0;
  const skipPercent = windows ? Math.round((stats.skipped_by_l1 / windows) * 100) : 0;

  return (
    <div className="grid cols-3">
      <Card
        className="layer l1"
        title="L1 · Person gate"
        aside={<Badge tone={healthTone(l1.detector.status)} dot>{l1.detector.status}</Badge>}
      >
        <div className="stat-row">
          <Stat value={`${skipPercent}%`} label="windows skipped" tone={skipPercent > 0 ? "ok" : "muted"} />
          <Stat value={stats.skipped_by_l1} label="skipped" small />
          <Stat value={l1.gate.fail_opens} label="fail-opens" small
                tone={l1.gate.fail_opens > 0 ? "warn" : "muted"} />
        </div>
        <p className="muted" style={{ margin: ".7rem 0 0", fontSize: 12.5 }}>
          <code>{l1.detector.detector_id}</code> · now{" "}
          <b>{l1.decision.decision}</b>{" "}
          <span className="mono">({l1.decision.reason})</span>
        </p>
        {l1.detector.note && <p className="muted" style={{ margin: ".3rem 0 0", fontSize: 12 }}>{l1.detector.note}</p>}
      </Card>

      <Card
        className="layer l2"
        title="L2 · Gemini"
        aside={<Badge tone={stats.l2_failures > 0 ? "warn" : "ok"} dot>
          {status.providers.l2.stub ? "stub" : "live"}
        </Badge>}
      >
        <div className="stat-row">
          <Stat value={stats.l2_calls} label="calls" />
          <Stat value={stats.heartbeats} label="heartbeat" small />
          <Stat value={stats.forced} label="forced" small tone={stats.forced > 0 ? "warn" : "muted"} />
          <Stat value={stats.l2_failures} label="failed" small tone={stats.l2_failures ? "bad" : "muted"} />
        </div>
        <div className="stat-row" style={{ marginTop: ".6rem" }}>
          <Stat value={ms(stats.l2_latency_avg)} label="avg latency" small />
          <Stat value={ms(stats.l2_latency_max)} label="max" small />
        </div>
        <p className="muted" style={{ margin: ".7rem 0 0", fontSize: 12.5 }}>
          <code>{l2.model ?? status.providers.l2.model}</code>
          {l2.queue.pending && <> · queue pending</>}
        </p>
      </Card>

      <Card
        className="layer l3"
        title="L3 · MiniMax"
        aside={<Badge tone={l3.enabled ? (status.providers.l3.stub ? "muted" : "ok") : "muted"} dot>
          {l3.enabled ? (status.providers.l3.stub ? "stub" : "live") : "disabled"}
        </Badge>}
      >
        <div className="stat-row">
          <Stat value={stats.escalations} label="escalations" tone={stats.escalations ? "warn" : "muted"} />
          <Stat value={stats.l3_calls} label="calls" small />
          <Stat value={stats.l3_degraded} label="text-only" small
                tone={stats.l3_degraded ? "warn" : "muted"} />
          <Stat value={stats.l3_failures} label="failed" small
                tone={stats.l3_failures ? "bad" : "muted"} />
        </div>
        <div className="stat-row" style={{ marginTop: ".6rem" }}>
          <Stat value={ms(stats.l3_latency_avg)} label="avg latency" small />
          <Stat value={l3.today} label="today" small />
        </div>
        <p className="muted" style={{ margin: ".7rem 0 0", fontSize: 12.5 }}>
          <code>{l3.model ?? status.providers.l3.model}</code>
          {l3.queue.pending_high_risk && <> · <b>high-risk pending</b></>}
        </p>
      </Card>
    </div>
  );
}
