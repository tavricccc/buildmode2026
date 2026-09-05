import { useState } from "react";
import type { DeploymentType } from "../../types/api";
import { modelEndpoints } from "../../api/model_endpoints";
import { Button } from "../../components/Button";

interface Props { onNext: () => void }

export default function ModelSource(_: Props) {
  const [kind, setKind] = useState<"local" | "cloud">("local");
  const [displayName, setDisplayName] = useState("Local Stub");
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:18181/v1");
  const [result, setResult] = useState<string>("");
  return (
    <div>
      <label>
        <input type="radio" checked={kind === "local"} onChange={() => setKind("local")} /> 本地 catalog
      </label>
      <label>
        <input type="radio" checked={kind === "cloud"} onChange={() => setKind("cloud")} /> 雲端 provider
      </label>
      <div>
        <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="display name" />
      </div>
      <div>
        <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="base URL" />
      </div>
      <Button
        onClick={async () => {
          const id = `${kind}-${Date.now()}`;
          await modelEndpoints.upsert({
            id,
            display_name: displayName,
            deployment_type: kind as DeploymentType,
            base_url: baseUrl,
            adapter_mode: "openai_chat",
          });
          const test = await modelEndpoints.test(id);
          setResult(JSON.stringify(test));
        }}
      >
        建立並測試
      </Button>
      {result ? <pre>{result}</pre> : null}
    </div>
  );
}
