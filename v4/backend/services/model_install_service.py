"""Model install service stub (v4 13).

Full implementation lands in commit 2. This round exposes the
typed surface for the API and tests; the actual catalog runtime
launcher is left to a later commit.
"""

from __future__ import annotations

from ..adapters.capability_probe import run_probe
from ..adapters.model_gateway import ModelEndpointRegistry
from ..adapters.openai_client import OpenAICompatibleClient
from ..domain.enums import Capability
from ..domain.ids import new_id
from ..domain.time import isoformat, utc_now
from ..state_machines.model_install import InstallContext, install_transition


class ModelInstallService:
    def __init__(self, registry: ModelEndpointRegistry) -> None:
        self._registry = registry

    async def start_install_job(
        self,
        *,
        endpoint_id: str,
        capability: str,
        remote_model_id: str,
        display_name: str,
    ) -> dict:
        return {
            "job_id": new_id("inst"),
            "status": "pending",
            "endpoint_id": endpoint_id,
            "capability": capability,
            "remote_model_id": remote_model_id,
            "display_name": display_name,
            "started_at": isoformat(utc_now()),
        }

    async def probe(
        self,
        *,
        endpoint_id: str,
        capability: str,
        remote_model_id: str,
    ) -> dict:
        endpoint = self._registry.get(endpoint_id)
        if endpoint is None:
            return {"ok": False, "code": "ENDPOINT_AUTH_FAILED", "detail": "unknown endpoint"}
        client = OpenAICompatibleClient(base_url=endpoint.base_url, api_key=None)
        result = await run_probe(client, Capability(capability), remote_model_id)
        return result.to_dict()

    def transition(self, ctx: InstallContext) -> str:
        return install_transition(ctx)
