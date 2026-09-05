import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { Badge, Card, Empty, ms, outcomeTone } from "../components/ui";
import type { CascadeTestResult, SetupState } from "../types/api";

type ProbeResult = { ok: boolean; code?: string; message?: string; model_available?: boolean };

/**
 * Setup (v5 03, v5 04).
 *
 * Nothing here downloads a model on page load. The order follows the
 * spec: check the runtime, pick a detector, configure the two model slots
 * independently, probe each layer on its own, and only then run one real
 * window through the whole cascade. Three green pings do not prove the
 * layers agree on a contract; the cascade test does.
 */
export function SetupPage({ onDone }: { onDone: () => void }) {
  const [state, setState] = useState<SetupState | null>(null);
  const [probes, setProbes] = useState<Record<string, ProbeResult | string>>({});
  const [cascade, setCascade] = useState<CascadeTestResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => setState(await api.setupState()), []);
  useEffect(() => { void load(); }, [load]);

  if (!state) return <Card title="Setup"><Empty>Loading…</Empty></Card>;

  const probe = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name);
    try {
      const result = await fn();
      setProbes((current) => ({ ...current, [name]: result as ProbeResult }));
    } catch (exc) {
      setProbes((current) => ({ ...current, [name]: (exc as Error).message }));
    } finally {
      setBusy(null);
      void load();
    }
  };

  const renderProbe = (name: string) => {
    const result = probes[name];
    if (result === undefined) return null;
    if (typeof result === "string") return <Badge tone="bad">{result}</Badge>;
    if (!result.ok) return <Badge tone="bad">{result.code}: {result.message}</Badge>;
    return <Badge tone={result.model_available === false ? "warn" : "ok"}>
      {result.model_available === false ? "reachable, but the configured model is not listed" : "reachable"}
    </Badge>;
  };

  return (
    <div className="stack">
      <Card title="Setup" aside={state.complete
        ? <Badge tone="ok">ready</Badge>
        : <Badge tone="warn">incomplete</Badge>}>
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
          The backend starts before any of this is configured, and nothing on this page downloads a
          model until you ask it to. Unconfigured model slots fall back to the offline stubs, so the
          cascade can be exercised end to end before a single key exists.
        </p>
        <div className="steps">
          {state.steps.map((step) => (
            <div className="step" key={step.id}>
              <span className="mark">{step.done ? "✅" : "⬜"}</span>
              <div className="body">
                <b>{step.label}</b>
                <div>{step.detail}</div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Probe each layer" aside={<span className="muted" style={{ fontSize: 12 }}>
        auth and reachability only — cheap, and safe to repeat
      </span>}>
        <div className="stack">
          <div className="row">
            <button className="action" disabled={busy !== null}
                    onClick={() => void probe("l1", () => api.testPersonGate())}>Test L1 detector</button>
            {renderProbe("l1")}
            {typeof probes["l1"] === "object" && <Badge tone="ok">detector answered</Badge>}
          </div>
          <div className="row">
            <button className="action" disabled={busy !== null}
                    onClick={() => void probe("l2", () => api.testGemini())}>Test L2 Gemini</button>
            {renderProbe("l2")}
          </div>
          <div className="row">
            <button className="action" disabled={busy !== null}
                    onClick={() => void probe("l3", () => api.testMinimax())}>Test L3 MiniMax</button>
            {renderProbe("l3")}
          </div>
        </div>
      </Card>

      <Card title="End-to-end cascade test" aside={<span className="muted" style={{ fontSize: 12 }}>
        one real window through all three layers
      </span>}>
        <div className="row" style={{ marginBottom: cascade ? ".9rem" : 0 }}>
          {state.scenarios.map((scenario) => (
            <button key={scenario} className="action primary" disabled={busy !== null}
                    onClick={() => void (async () => {
                      setBusy("cascade");
                      try { setCascade(await api.cascadeTest(scenario)); }
                      finally { setBusy(null); }
                    })()}>
              Run “{scenario}”
            </button>
          ))}
        </div>
        {cascade && (
          <div className="trace">
            {cascade.trace.map((step) => (
              <div key={step.layer} className={`trace-step ${step.layer.toLowerCase()}`}>
                <div className="layer">{step.layer}</div>
                <div className="outcome" style={{ color: `var(--${outcomeTone(step.outcome)})` }}>
                  {step.outcome}
                </div>
                <div className="detail">{step.detail} · {ms(Number(step.latency_ms))}</div>
              </div>
            ))}
          </div>
        )}
        {cascade?.l2.error && <p className="banner bad" style={{ marginTop: ".7rem" }}>L2: {cascade.l2.error}</p>}
        {cascade?.l3.error && <p className="banner bad" style={{ marginTop: ".7rem" }}>L3: {cascade.l3.error}</p>}
      </Card>

      <div className="row">
        <button className="action primary" onClick={onDone}>Go to the Dashboard →</button>
      </div>
    </div>
  );
}
