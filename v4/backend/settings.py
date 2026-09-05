"""Application configuration.

Read once at process start. The class is intentionally frozen: any change
must go through the settings service and produce a new config version
(see ``backend/services/settings_service.py``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
V4_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = V4_ROOT / "data"
CATALOG_PATH = DATA_DIR / "catalog" / "local_models.json"
REPLAY_MANIFEST = DATA_DIR / "replays" / "manifest.json"


@dataclass(frozen=True)
class AppSettings:
    """Static, host-managed configuration.

    Only fields whose owner is the host process live here. Runtime-tunable
    configuration (loop interval, thresholds, retention, etc.) lives in
    ``config_versions`` and is exposed via the Settings API.
    """

    bind_host: str = "127.0.0.1"
    bind_port: int = 8000
    log_level: str = "info"

    # Database
    db_path: Path = V4_ROOT / "data" / "v4.sqlite"

    # Media / catalog
    media_root: Path = DATA_DIR / "captures"
    catalog_path: Path = CATALOG_PATH
    replay_manifest_path: Path = REPLAY_MANIFEST

    # Secret store (write-only; only fingerprints are read back)
    secret_store_path: Path = V4_ROOT / "data" / "secrets.json"

    # Local stub OpenAI-compatible server
    stub_enabled: bool = True
    stub_host: str = "127.0.0.1"
    stub_port: int = 18181

    # Defaults for first-run
    default_subject_id: str = "resident_demo"
    default_resident_name: str = "Demo Resident"

    @classmethod
    def from_env(cls) -> "AppSettings":
        overrides: dict[str, object] = {}
        if host := os.environ.get("V4_BIND_HOST"):
            overrides["bind_host"] = host
        if port := os.environ.get("V4_BIND_PORT"):
            overrides["bind_port"] = int(port)
        if level := os.environ.get("V4_LOG_LEVEL"):
            overrides["log_level"] = level
        if db := os.environ.get("V4_DB_PATH"):
            overrides["db_path"] = Path(db)
        if stub_port := os.environ.get("V4_STUB_PORT"):
            overrides["stub_port"] = int(stub_port)
        if "V4_STUB_ENABLED" in os.environ:
            overrides["stub_enabled"] = os.environ["V4_STUB_ENABLED"].lower() in {"1", "true", "yes"}
        return cls(**overrides)
