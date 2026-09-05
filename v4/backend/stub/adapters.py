"""Adapter hints for cloud providers.

In commit 1 this is a typed mapping (which ``adapter_mode`` produces
which payload shape). Real adapter implementations land in a later
commit; for now every adapter is the same OpenAI chat-completions
contract.
"""

from __future__ import annotations


_OPENAI_MODES = {"openai_chat", "openai_chat_image"}


def is_openai_compatible(adapter_mode: str) -> bool:
    return adapter_mode in _OPENAI_MODES
