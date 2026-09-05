import { useEffect, useState } from "react";
import { modelEndpoints, installedModels, catalog } from "../../api/model_endpoints";
import { Button } from "../../components/Button";

interface Props { onNext: () => void }

export default function VisionModel(_: Props) {
  const [endpoints, setEndpoints] = useState<Array<{ id: string; display_name: string }>>([]);
  const [catalogEntries, setCatalogEntries] = useState<Array<{ id: string; display_name: string }>>([]);
  const [endpointId, setEndpointId] = useState("");
  const [modelId, setModelId] = useState("vision-stub");
  const [status, setStatus] = useState<string>("");
  useEffect(() => {
    modelEndpoints.list().then((r) => setEndpoints(r.endpoints));
    catalog.list().then((r) => setCatalogEntries(r.models));
  }, []);
  return (
    <div>
      <label>Endpoint:
        <select value={endpointId} onChange={(e) => setEndpointId(e.target.value)}>
          <option value="">選擇 endpoint</option>
          {endpoints.map((e) => <option key={e.id} value={e.id}>{e.display_name}</option>)}
        </select>
      </label>
      <div>
        <input value={modelId} onChange={(e) => setModelId(e.target.value)} placeholder="model id" />
      </div>
      <Button
        onClick={async () => {
          const r = await installedModels.install({
            endpoint_id: endpointId,
            capability: "vision",
            remote_model_id: modelId,
            display_name: modelId,
            source_type: "cloud_provider",
          });
          setStatus(JSON.stringify(r));
        }}
      >
        安裝並 probe
      </Button>
      {status ? <pre>{status}</pre> : null}
      <h4>本地 catalog</h4>
      <ul>{catalogEntries.map((c) => <li key={c.id}>{c.display_name} ({c.id})</li>)}</ul>
    </div>
  );
}
