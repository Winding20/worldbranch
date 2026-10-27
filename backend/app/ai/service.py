"""AI 分析服务：把「材料 → 提示词 → 模型 → 带引用的回答」串起来。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Branch, LlmProvider
from . import context as context_mod
from .providers import LLMConfig, LLMError, build_client


class ProviderNotConfigured(RuntimeError):
    pass


def get_provider(session: Session, provider_id: int | None = None) -> LlmProvider | None:
    if provider_id is not None:
        return session.get(LlmProvider, provider_id)
    return session.scalar(
        select(LlmProvider)
        .where(LlmProvider.enabled.is_(True))
        .order_by(LlmProvider.is_default.desc(), LlmProvider.id)
    )


def resolve_config(
    provider: LlmProvider | None,
    api_key: str = "",
    *,
    model: str | None = None,
) -> LLMConfig:
    """组装调用配置。Key 只在这一刻存在于内存里。"""
    if provider is None:
        raise ProviderNotConfigured(
            "还没有配置模型服务。请在设置里填写你自己的 API Key 与接口地址。"
        )
    return LLMConfig(
        kind=provider.kind,
        base_url=provider.base_url,
        model=model or provider.model,
        api_key=api_key,
    )


def analyze(
    session: Session,
    branch: Branch,
    *,
    question: str = "",
    event_id: int | None = None,
    provider: LlmProvider | None = None,
    api_key: str = "",
    model: str | None = None,
) -> dict[str, Any]:
    """执行一次分析。返回回答 + 引用 + 用到的材料摘要。"""
    ctx = context_mod.build_context(
        session, branch, question=question, event_id=event_id
    )
    messages = context_mod.build_messages(ctx, question)

    config = resolve_config(provider, api_key, model=model)
    client = build_client(config)

    try:
        answer = client.chat(messages)
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"调用模型失败：{type(exc).__name__}") from exc

    return {
        "answer": answer,
        "citations": ctx["citation_list"],
        "provider": {
            "name": provider.name if provider else "mock",
            "kind": config.kind,
            "model": config.model,
        },
        "context": {
            "branch_date": ctx["branch"]["date"],
            "region_count": len(ctx["regions"]),
            "event_count": len(ctx["recent_events"]),
            "knowledge_hits": len(ctx["knowledge"]),
            "focus_event": ctx["focus_event"]["title"] if ctx["focus_event"] else None,
            "cause_chain_length": len(ctx["cause_chain"]),
        },
        # 便于排查：材料原文（不含 Key）
        "material_preview": context_mod.format_context(ctx)[:1200],
    }