import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { Badge, Card, Empty, ErrorBanner, errorText, ms, outcomeTone } from "../components/ui";
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
  const [cascadeError, setCascadeError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setState(await api.setupState()); setLoadError(null); }
    catch (exc) { setLoadError(errorText(exc)); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  if (loadError && !state) return <Card title="初始設定"><ErrorBanner>無法讀取設定狀態：{loadError}</ErrorBanner></Card>;
  if (!state) return <Card title="初始設定"><Empty>載入中…</Empty></Card>;

  const probe = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name);
    try {
      const result = await fn();
      setProbes((current) => ({ ...current, [name]: result as ProbeResult }));
    } catch (exc) {
      setProbes((current) => ({ ...current, [name]: errorText(exc) }));
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
      {result.model_available === false ? "服務可連線，但找不到指定模型" : "連線正常"}
    </Badge>;
  };

  return (
    <div className="stack">
      <header className="page-heading"><div><span className="eyebrow">Setup Wizard</span><h1>初始設定</h1><p>逐層確認環境、模型與完整 Cascade，不以單一綠燈代替端到端驗證。</p></div></header>
      <Card title="設定進度" aside={state.complete
        ? <Badge tone="ok">已就緒</Badge>
        : <Badge tone="warn">尚未完成</Badge>}>
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
          即使尚未設定模型，後端仍可啟動。未設定的模型槽會使用 offline stub 驗證資料契約，
          但不代表真實模型能力；任何模型下載都必須由你主動觸發。
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

      <Card title="逐層連線測試" aside={<span className="muted" style={{ fontSize: 12 }}>
        僅測試驗證與可用性，可安全重複
      </span>}>
        <div className="stack">
          <div className="row">
            <button className="action" disabled={busy !== null}
                    onClick={() => void probe("l1", () => api.testPersonGate())}>測試 L1 detector</button>
            {renderProbe("l1")}
            {typeof probes["l1"] === "object" && <Badge tone="ok">Detector 已回應</Badge>}
          </div>
          <div className="row">
            <button className="action" disabled={busy !== null}
                    onClick={() => void probe("l2", () => api.testGemini())}>測試 L2 Gemini</button>
            {renderProbe("l2")}
          </div>
          <div className="row">
            <button className="action" disabled={busy !== null}
                    onClick={() => void probe("l3", () => api.testMinimax())}>測試 L3 MiniMax</button>
            {renderProbe("l3")}
          </div>
        </div>
      </Card>

      <Card title="端到端 Cascade 測試" aside={<span className="muted" style={{ fontSize: 12 }}>
        讓一個真實分析視窗通過全部三層
      </span>}>
        <div className="row" style={{ marginBottom: cascade || cascadeError ? ".9rem" : 0 }}>
          {state.scenarios.map((scenario) => (
            <button key={scenario} className="action primary" disabled={busy !== null}
                    onClick={() => void (async () => {
                      setBusy("cascade");
                      setCascadeError(null);
                      // Clearing the old trace matters: a stale green cascade
                      // left on screen after a failed run reads as a pass.
                      setCascade(null);
                      try { setCascade(await api.cascadeTest(scenario)); }
                      catch (exc) { setCascadeError(errorText(exc)); }
                      finally { setBusy(null); }
                    })()}>
              執行「{scenario}」
            </button>
          ))}
        </div>
        {cascadeError && <ErrorBanner>Cascade 測試未完成：{cascadeError}</ErrorBanner>}
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
        <button className="action primary" onClick={onDone}>前往照護總覽 →</button>
      </div>
    </div>
  );
}
