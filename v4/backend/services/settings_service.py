"""Settings service (v4 02, 05, 06).

Implements optimistic concurrency: every PATCH must carry
``base_version``. Conflicts are returned as ``SettingsError`` which
the API layer maps onto HTTP 409 + ``CONFIG_VERSION_CONFLICT``.

High-risk patches (lower fall confidence, change of notification
recipients, etc.) are returned with ``requires_confirmation=True``;
the second call must include the same patch and a confirm flag.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

from ..domain.ids import new_id
from ..domain.policy import PolicyBundle
from ..domain.time import isoformat, utc_now
from ..policy import DeterministicPolicyGateway
from ..realtime import RealtimeBroadcaster
from ..repos.config_version_repo import ConfigVersionRepo
from ..repos.session import session_scope
from ..state_machines.config_apply import ConfigApplyContext, config_apply_transition


logger = logging.getLogger(__name__)


class SettingsError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class SettingsService:
    def __init__(self, broadcaster: RealtimeBroadcaster) -> None:
        self._broadcaster = broadcaster
        self._policy = DeterministicPolicyGateway()
        self._active: tuple[str, PolicyBundle] | None = None

    # ------------------------------------------------------------------
    # Schema / current
    # ------------------------------------------------------------------

    def schema(self) -> dict[str, Any]:
        """Return JSON-Schema-ish metadata for the UI."""
        return {
            "schema_version": "policy.v1",
            "categories": {
                "ui_editable": [k for k in self._editable_keys()],
                "secret_write_only": ["notification.bot_token"],
                "host_managed": ["bind", "db_path", "secret_store_path", "media_root"],
            },
            "defaults": PolicyBundle().model_dump(mode="json"),
        }

    def _editable_keys(self) -> list[str]:
        bundle = PolicyBundle()
        keys: list[str] = []
        for section in (
            "fall", "hydration", "analysis", "observer",
            "notification", "vision_loop", "audio",
        ):
            model = getattr(bundle, section)
            keys.extend(f"{section}.{name}" for name in model.model_fields)
        keys.extend(["locale", "timezone"])
        return keys

    async def active_version(self) -> str | None:
        if self._active is not None:
            return self._active[0]
        async with session_scope() as session:
            repo = ConfigVersionRepo(session)
            latest = await repo.latest_activated()
        if latest is None:
            return None
        bundle = PolicyBundle.model_validate_json(latest.settings_json)
        self._active = (latest.id, bundle)
        return latest.id

    async def active_bundle(self) -> PolicyBundle:
        if self._active is not None:
            return self._active[1]
        version = await self.active_version()
        if version is None:
            return PolicyBundle()
        return self._active[1]  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Draft / test / apply / versions / rollback
    # ------------------------------------------------------------------

    async def draft(
        self,
        patch: dict[str, Any],
        base_version: str | None,
        created_by: str = "ui",
    ) -> dict[str, Any]:
        current = await self.active_bundle()
        merged = copy.deepcopy(current.model_dump(mode="json"))
        _deep_merge(merged, patch)
        validation_errors = _validate_bundle(merged)
        flat_patch = _flatten(patch)
        decision = self._policy.evaluate(flat_patch, current)
        draft_id = new_id("drf")
        async with session_scope() as session:
            repo = ConfigVersionRepo(session)
            await repo.insert(
                version_id=draft_id,
                base_version=base_version,
                settings=merged,
                changed_keys=list(flat_patch.keys()),
                created_by=created_by,
                created_at=isoformat(utc_now()),
                activated_at=None,
                rolled_back_from=None,
            )
        return {
            "draft_id": draft_id,
            "validation_errors": validation_errors,
            "requires_confirmation": decision.requires_confirmation,
            "restart_required": decision.restart_required,
            "preview": merged,
        }

    async def test(self, draft_id: str) -> dict[str, Any]:
        async with session_scope() as session:
            repo = ConfigVersionRepo(session)
            record = await repo.get(draft_id)
        if record is None:
            raise SettingsError("CONFIG_VERSION_CONFLICT", f"unknown draft {draft_id}")
        settings = json.loads(record.settings_json)
        # The "test" runs all integration-style dry checks. For commit 1
        # we just confirm the bundle validates as PolicyBundle.
        try:
            PolicyBundle.model_validate(settings)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "failures": [str(exc)]}
        return {"ok": True, "failures": []}

    async def apply(
        self,
        draft_id: str,
        base_version: str,
        confirm: bool = False,
        created_by: str = "ui",
    ) -> dict[str, Any]:
        active = await self.active_version()
        if (active or "") != (base_version or ""):
            raise SettingsError(
                "CONFIG_VERSION_CONFLICT",
                f"base_version={base_version} active={active}",
            )
        async with session_scope() as session:
            repo = ConfigVersionRepo(session)
            record = await repo.get(draft_id)
        if record is None:
            raise SettingsError("CONFIG_VERSION_CONFLICT", f"unknown draft {draft_id}")
        settings = json.loads(record.settings_json)
        try:
            bundle = PolicyBundle.model_validate(settings)
        except Exception as exc:  # noqa: BLE001
            raise SettingsError("MODEL_SCHEMA_INVALID", f"settings invalid: {exc}") from exc

        flat = json.loads(record.changed_keys_json)
        decision = self._policy.evaluate({k: True for k in flat}, bundle)
        if decision.requires_confirmation and not confirm:
            return {
                "status": "requires_confirmation",
                "reason": decision.reason,
                "restart_required": decision.restart_required,
            }

        new_version = new_id("cfg")
        context = ConfigApplyContext(
            base_version=base_version,
            current_version=active,
            validation_errors=(),
            test_failures=(),
            requires_restart=decision.restart_required,
        )
        outcome = config_apply_transition(context)
        if outcome in {"validation_failed", "conflict", "test_failed"}:
            raise SettingsError("CONFIG_VERSION_CONFLICT", outcome)

        async with session_scope() as session:
            repo = ConfigVersionRepo(session)
            await repo.insert(
                version_id=new_version,
                base_version=base_version,
                settings=settings,
                changed_keys=flat,
                created_by=created_by,
                created_at=isoformat(utc_now()),
                activated_at=isoformat(utc_now()),
                rolled_back_from=None,
            )
        self._active = (new_version, bundle)
        await self._broadcaster.broadcast(
            "settings.applied",
            {
                "version_id": new_version,
                "base_version": base_version,
                "restart_required": decision.restart_required,
            },
        )
        return {
            "status": outcome,
            "version_id": new_version,
            "restart_required": decision.restart_required,
        }

    async def list_versions(self) -> list[dict[str, Any]]:
        async with session_scope() as session:
            repo = ConfigVersionRepo(session)
            records = await repo.list_all()
        return [
            {
                "id": r.id,
                "base_version": r.base_version,
                "created_by": r.created_by,
                "created_at": r.created_at,
                "activated_at": r.activated_at,
                "rolled_back_from": r.rolled_back_from,
            }
            for r in records
        ]

    async def rollback(self, version_id: str, created_by: str = "ui") -> dict[str, Any]:
        async with session_scope() as session:
            repo = ConfigVersionRepo(session)
            record = await repo.get(version_id)
        if record is None:
            raise SettingsError("CONFIG_VERSION_CONFLICT", f"unknown version {version_id}")
        settings = json.loads(record.settings_json)
        bundle = PolicyBundle.model_validate(settings)
        new_version = new_id("cfg")
        active = await self.active_version()
        async with session_scope() as session:
            repo = ConfigVersionRepo(session)
            await repo.insert(
                version_id=new_version,
                base_version=active,
                settings=settings,
                changed_keys=["__rollback__"],
                created_by=created_by,
                created_at=isoformat(utc_now()),
                activated_at=isoformat(utc_now()),
                rolled_back_from=version_id,
            )
        self._active = (new_version, bundle)
        await self._broadcaster.broadcast(
            "settings.rollback.completed",
            {"version_id": new_version, "rolled_back_from": version_id},
        )
        return {"version_id": new_version, "rolled_back_from": version_id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deep_merge(into: dict, patch: dict) -> None:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(into.get(k), dict):
            _deep_merge(into[k], v)
        else:
            into[k] = v


def _flatten(patch: dict, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in patch.items():
        full = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, full))
        else:
            out[full] = v
    return out


def _validate_bundle(settings: dict) -> list[str]:
    try:
        PolicyBundle.model_validate(settings)
        return []
    except Exception as exc:  # noqa: BLE001
        return [str(exc)]
