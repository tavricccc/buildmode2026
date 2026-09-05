interface Props { onNext: () => void }

export default function Review(_: Props) {
  return (
    <div>
      <p>本地下載大小（local）或 data destination（cloud）、請求頻率、變更摘要、secret 狀態皆於 commit 2 顯示。</p>
    </div>
  );
}
