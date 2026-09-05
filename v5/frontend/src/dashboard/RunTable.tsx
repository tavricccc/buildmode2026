import { Badge, Card, Empty, clock, ms, outcomeTone, riskTone } from "../components/ui";
import type { PipelineRun } from "../types/api";

/**
 * Every window, whatever happened to it — including the ones that were
 * skipped. Showing skips is the point: a pipeline that only logs its
 * calls cannot show you that it saved anything, or that it stopped
 * looking (v5 00 item 10).
 */
export function RunTable({ runs, onSelectEvent }: {
  runs: PipelineRun[];
  onSelectEvent: (eventId: string) => void;
}) {
  if (runs.length === 0) {
    return <Card title="Pipeline Runs"><Empty>尚無分析視窗，請先啟動影像來源。</Empty></Card>;
  }
  return (
    <Card title="Pipeline Runs" aside={<span className="muted mono">最近 {runs.length} 筆</span>}>
      <div className="scroll">
        <table>
          <thead>
            <tr>
              <th>時間</th><th>L1</th><th>L2</th><th>L3</th><th>原因</th><th>延遲</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const eventId = run.event_ids[0];
              return (
                <tr
                  key={run.run_id}
                  className={eventId ? "clickable" : undefined}
                  onClick={eventId ? () => onSelectEvent(eventId) : undefined}
                >
                  <td className="mono">{clock(run.window_ended_at_ms)}</td>
                  <td><Badge tone={run.l1_decision === "person_present" ? "ok"
                    : run.l1_decision === "no_person" ? "muted" : "warn"}>{run.l1_decision}</Badge></td>
                  <td>
                    <Badge tone={outcomeTone(run.l2_outcome)}>{run.l2_outcome}</Badge>
                    {run.l2_repaired && <> <Badge tone="warn">repaired</Badge></>}
                  </td>
                  <td>
                    <Badge tone={outcomeTone(run.l3_outcome)}>{run.l3_outcome}</Badge>
                    {run.l3_risk_level && <> <Badge tone={riskTone(run.l3_risk_level)}>{run.l3_risk_level}</Badge></>}
                  </td>
                  <td className="muted" style={{ maxWidth: "20rem" }}>
                    {run.l2_error ?? run.l3_error ?? run.l2_escalation_reasons.join(", ") ?? ""}
                    {!run.l2_error && !run.l3_error && run.l2_escalation_reasons.length === 0 && run.l2_reason}
                  </td>
                  <td className="mono">{ms((run.l2_latency_ms ?? 0) + (run.l3_latency_ms ?? 0))}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
