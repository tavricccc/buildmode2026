export function LoadingState({ label = "載入中…" }: { label?: string }) {
  return <div className="loading">{label}</div>;
}
