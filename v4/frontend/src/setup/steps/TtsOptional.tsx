import type { ReactNode } from "react";

interface Props { onNext: () => void }

export default function TtsOptional(_: Props): ReactNode {
  return <p>可選：安裝並測試 <code>/v1/audio/speech</code>，或保持停用。</p>;
}
