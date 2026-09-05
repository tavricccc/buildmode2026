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
    <section className="pipeline-flow" aria-label="三層分析與授權管線">
      <Card
        className="layer l1"
        title="L1 · Person gate"
        aside={<Badge tone={healthTone(l1.detector.status)} dot>{l1.detector.status}</Badge>}
      >
        <div className="stat-row">
          <Stat value={`${skipPercent}%`} label="安全跳過率" tone={skipPercent > 0 ? "ok" : "muted"} />
          <Stat value={stats.skipped_by_l1} label="已跳過" small />
          <Stat value={l1.gate.fail_opens} label="Fail-open" small
                tone={l1.gate.fail_opens > 0 ? "warn" : "muted"} />
        </div>
        <p className="muted" style={{ margin: ".7rem 0 0", fontSize: 12.5 }}>
          <code>{l1.detector.detector_id}</code> · 目前{" "}
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
          <Stat value={stats.l2_calls} label="呼叫" />
          <Stat value={stats.heartbeats} label="Heartbeat" small />
          <Stat value={stats.forced} label="強制觀察" small tone={stats.forced > 0 ? "warn" : "muted"} />
          <Stat value={stats.l2_failures} label="失敗" small tone={stats.l2_failures ? "bad" : "muted"} />
        </div>
        <div className="stat-row" style={{ marginTop: ".6rem" }}>
          <Stat value={ms(stats.l2_latency_avg)} label="平均延遲" small />
          <Stat value={ms(stats.l2_latency_max)} label="最大延遲" small />
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
          <Stat value={stats.escalations} label="升級" tone={stats.escalations ? "warn" : "muted"} />
          <Stat value={stats.l3_calls} label="呼叫" small />
          <Stat value={stats.l3_degraded} label="僅文字降級" small
                tone={stats.l3_degraded ? "warn" : "muted"} />
          <Stat value={stats.l3_failures} label="失敗" small
                tone={stats.l3_failures ? "bad" : "muted"} />
        </div>
        <div className="stat-row" style={{ marginTop: ".6rem" }}>
          <Stat value={ms(stats.l3_latency_avg)} label="平均延遲" small />
          <Stat value={l3.today} label="今日" small />
        </div>
        <p className="muted" style={{ margin: ".7rem 0 0", fontSize: 12.5 }}>
          <code>{l3.model ?? status.providers.l3.model}</code>
          {l3.queue.pending_high_risk && <> · <b>high-risk pending</b></>}
        </p>
      </Card>
      <div className="policy-node"><span>唯一授權層</span><b>Deterministic<br />Policy Gateway</b><small>模型只建議，Policy 才授權</small></div>
    </section>
  );
}
