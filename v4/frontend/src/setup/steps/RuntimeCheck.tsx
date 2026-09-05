import { useEffect, useState } from "react";
import { setup } from "../../api/status";

interface Props { onNext: () => void }

export default function RuntimeCheck(_: Props) {
  const [prereq, setPrereq] = useState<{ items: Array<{ name: string; ok: boolean; detail: string }> } | null>(null);
  useEffect(() => {
    setup.prerequisites().then(setPrereq).catch(() => setPrereq({ items: [] }));
  }, []);
  if (!prereq) return <p>讀取 prerequisites…</p>;
  return (
    <ul>
      {prereq.items.map((item) => (
        <li key={item.name}>
          <strong>{item.name}</strong>: {item.ok ? "OK" : "缺少"} ({item.detail})
        </li>
      ))}
    </ul>
  );
}
