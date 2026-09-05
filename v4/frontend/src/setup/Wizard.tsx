import { useState } from "react";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { StepNav } from "./steps/StepNav";
import RuntimeCheck from "./steps/RuntimeCheck";
import ModelSource from "./steps/ModelSource";
import VisionModel from "./steps/VisionModel";
import AsrModel from "./steps/AsrModel";
import AnalysisModel from "./steps/AnalysisModel";
import TtsOptional from "./steps/TtsOptional";
import CareSettings from "./steps/CareSettings";
import Review from "./steps/Review";

const STEPS = [
  { id: "runtime", title: "Runtime", component: RuntimeCheck },
  { id: "source", title: "Model source", component: ModelSource },
  { id: "vision", title: "Vision", component: VisionModel },
  { id: "asr", title: "ASR", component: AsrModel },
  { id: "analysis", title: "Analysis", component: AnalysisModel },
  { id: "tts", title: "TTS (optional)", component: TtsOptional },
  { id: "care", title: "Care settings", component: CareSettings },
  { id: "review", title: "Review", component: Review },
];

export default function SetupWizard() {
  const [index, setIndex] = useState(0);
  const Step = STEPS[index].component;
  return (
    <div className="setup-wizard">
      <h2>Setup Wizard</h2>
      <StepNav steps={STEPS.map((s) => s.title)} current={index} onJump={setIndex} />
      <Card title={STEPS[index].title}>
        <Step onNext={() => setIndex((i) => Math.min(i + 1, STEPS.length - 1))} />
      </Card>
      <div className="step-actions">
        <Button variant="secondary" disabled={index === 0} onClick={() => setIndex((i) => i - 1)}>
          上一步
        </Button>
        <Button disabled={index === STEPS.length - 1} onClick={() => setIndex((i) => i + 1)}>
          下一步
        </Button>
      </div>
    </div>
  );
}
