import type { ReactNode } from "react";

interface Props { onNext: () => void }

export default function AnalysisModel(_: Props): ReactNode {
  return <p>選擇並安裝 analysis 模型（commit 2 接上 catalog runtime）。</p>;
}
