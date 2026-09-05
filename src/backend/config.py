"""Runtime configuration (docs/03_API_AND_FRONTEND.md §Setup/Settings, docs/04_SETUP_DEPLOY_VERIFY.md).

The split matters: settings a caregiver may change from the browser live
in :class:`~backend.domain.policy.CarePolicy` and are versioned in SQLite;
settings that decide where the process binds and where data lands are
host-managed and live here, sourced from the environment only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .secretstore import SecretStore

REPO_ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class ProviderConfig:
    """One model slot. L2 and L3 are configured independently by design.

    This design drops the earlier "every model is an OpenAI-compatible endpoint" premise:
    Gemini is called through Google's own REST shape and MiniMax through
    an OpenAI-compatible one, and pretending otherwise cost v4 a working
    audio path. Each slot therefore carries its own base URL and style.
    """

    name: str
    model: str
    base_url: str
    api_style: str  # "gemini" | "openai"
    secret_key: str
    timeout_sec: float = 60.0
    enabled: bool = True

    def describe(self, store: SecretStore) -> dict[str, object]:
        return {
            "name": self.name,
            "model": self.model,
            "base_url": self.base_url,
            "api_style": self.api_style,
            "enabled": self.enabled,
            "timeout_sec": self.timeout_sec,
            "key_configured": store.configured(self.secret_key),
        }


@dataclass
class AppConfig:
    host: str = field(default_factory=lambda: _env("CARE_HOST", "127.0.0.1"))
    # Keep the care API separate from the local vLLM OpenAI endpoint.
    port: int = field(default_factory=lambda: _env_int("CARE_PORT", 8200))
    data_dir: Path = field(default_factory=lambda: Path(_env("CARE_DATA_DIR", str(REPO_ROOT / "data"))))
    db_path: Path = field(init=False)
    clips_dir: Path = field(init=False)
    secret_path: Path = field(init=False)
    subject_id: str = field(default_factory=lambda: _env("CARE_SUBJECT_ID", "subject-1"))
    observer_interval_sec: int = field(
        default_factory=lambda: _env_int("CARE_OBSERVER_INTERVAL_SEC", 900)
    )
    #: Gemini's documented inline_data ceiling; larger media needs Files API.
    inline_limit_bytes: int = 20 * 1024 * 1024
    static_dir: Path = field(default_factory=lambda: REPO_ROOT / "frontend" / "dist")

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.db_path = Path(_env("CARE_DB_PATH", str(self.data_dir / "care.sqlite3")))
        self.clips_dir = self.data_dir / "clips"
        self.secret_path = self.data_dir / "secrets.json"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.clips_dir, self.db_path.parent):
            path.mkdir(parents=True, exist_ok=True)

    def secret_store(self) -> SecretStore:
        return SecretStore(self.secret_path)


#: Which providers may occupy each slot. L2 and L3 stay independent by
#: design (docs/03_API_AND_FRONTEND.md), so the menus are separate rather than one shared list.
SLOT_PROVIDERS: dict[str, tuple[str, ...]] = {
    "l2": ("local_vllm", "gemini"),
    "l3": ("local_vllm", "minimax"),
}

#: Shown in Settings so the operator sees what a slot will need before
#: switching to it, rather than after the first failed call.
PROVIDER_LABELS: dict[str, str] = {
    "local_vllm": "本機 vLLM",
    "gemini": "Gemini",
    "minimax": "MiniMax",
}


def _gemini_config() -> ProviderConfig:
    return ProviderConfig(
        name="gemini",
        model=_env("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        base_url=_env("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
        api_style="gemini",
        secret_key="GEMINI_API_KEY",
        timeout_sec=_env_float("GEMINI_TIMEOUT_SEC", 45.0),
    )


def _minimax_config() -> ProviderConfig:
    return ProviderConfig(
        name="minimax",
        model=_env("MINIMAX_MODEL", "MiniMaxAI/MiniMax-M3"),
        base_url=_env("MINIMAX_BASE_URL", "https://api.gmi-serving.com/v1"),
        api_style="openai",
        secret_key="MINIMAX_API_KEY",
        timeout_sec=_env_float("MINIMAX_TIMEOUT_SEC", 90.0),
    )


def _local_vllm_config() -> ProviderConfig:
    return ProviderConfig(
        name="local_vllm",
        model=_env("VLLM_MODEL", "nemotron_omni"),
        base_url=_env("VLLM_BASE_URL", "http://127.0.0.1:8000/v1"),
        api_style="openai",
        secret_key="VLLM_API_KEY",
        timeout_sec=_env_float("VLLM_TIMEOUT_SEC", 90.0),
        enabled=_env("VLLM_ENABLED", "true").lower() not in {"0", "false", "no", "off"},
    )


_BUILDERS = {
    "gemini": _gemini_config,
    "minimax": _minimax_config,
    "local_vllm": _local_vllm_config,
}


def provider_config(slot: str, name: str) -> ProviderConfig:
    """Fresh defaults for one provider in one slot.

    Settings switches a slot by replacing its config wholesale rather than
    patching ``name``: a base URL, an API style and a secret key belong to
    a provider, and carrying a vLLM URL into a Gemini slot would leave a
    configuration that looks valid and cannot work.
    """
    allowed = SLOT_PROVIDERS.get(slot, ())
    if name not in allowed:
        raise ValueError(f"{name!r} is not available for {slot}; choose one of {allowed}")
    return _BUILDERS[name]()


def default_l2() -> ProviderConfig:
    name = _env("L2_PROVIDER", "local_vllm").lower()
    return provider_config("l2", name if name in SLOT_PROVIDERS["l2"] else "local_vllm")


def default_l3() -> ProviderConfig:
    name = _env("L3_PROVIDER", "local_vllm").lower()
    return provider_config("l3", name if name in SLOT_PROVIDERS["l3"] else "local_vllm")
