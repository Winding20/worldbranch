"""AI 分析层。

对外只暴露高层接口；厂商相关细节全部收敛在 ``providers`` 里。
"""

from __future__ import annotations

from .context import build_context, build_messages, format_context
from .knowledge import chunk_text, list_docs, search, upsert_doc
from .providers import LLMConfig, LLMError, build_client, known_kinds
from .service import ProviderNotConfigured, analyze, get_provider, resolve_config

__all__ = [
    "LLMConfig",
    "LLMError",
    "ProviderNotConfigured",
    "analyze",
    "build_client",
    "build_context",
    "build_messages",
    "chunk_text",
    "format_context",
    "get_provider",
    "known_kinds",
    "list_docs",
    "resolve_config",
    "search",
    "upsert_doc",
]