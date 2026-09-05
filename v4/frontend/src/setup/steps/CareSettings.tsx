import type { ReactNode } from "react";

interface Props { onNext: () => void }

export default function CareSettings(_: Props): ReactNode {
  return <p>Camera/audio、loop、事件、飲水、Observer、retention、Telegram（commit 2 連表單）。</p>;
}
