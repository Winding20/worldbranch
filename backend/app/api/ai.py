"""AI 相关接口：模型服务配置、知识库、分析。"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..ai import (
    analyze,
    get_provider,
    known_kinds,
    list_docs,
    search,
    upsert_doc,
)
from ..app_factory import get_db
from ..models import KnowledgeDoc, LlmProvider
from ..services import get_branch, get_world_by_key

bp = Blueprint("ai", __name__, url_prefix="/api/ai")

#: 浏览器把用户自己的 Key 放在这个头里，服务端用完即弃
KEY_HEADER = "X-LLM-Key"


# --------------------------------------------------------------------------- #
# 模型服务配置（不保存 Key）
# --------------------------------------------------------------------------- #
@bp.get("/kinds")
def kinds():
    return jsonify({"kinds": known_kinds()})


@bp.get("/providers")
def providers():
    with get_db().session() as session:
        rows = list(session.query(LlmProvider).order_by(LlmProvider.id))
        return jsonify([p.to_dict() for p in rows])


@bp.post("/providers")
def upsert_provider():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("name 不能为空")
    kind = payload.get("kind", "openai_compatible")
    if kind not in known_kinds():
        raise ValueError(f"不支持的适配器类型: {kind}")

    with get_db().session() as session:
        row = session.query(LlmProvider).filter_by(name=name).one_or_none()
        if row is None:
            row = LlmProvider(name=name)
            session.add(row)
        row.kind = kind
        row.base_url = (payload.get("base_url") or "").strip()
        row.model = (payload.get("model") or "").strip()
        row.enabled = bool(payload.get("enabled", True))
        if payload.get("is_default"):
            session.query(LlmProvider).update({LlmProvider.is_default: False})
            row.is_default = True
        session.flush()
        return jsonify(row.to_dict()), 201


@bp.delete("/providers/<int:provider_id>")
def delete_provider(provider_id: int):
    with get_db().session() as session:
        row = session.get(LlmProvider, provider_id)
        if row is None:
            raise LookupError("模型服务不存在")
        session.delete(row)
        return jsonify({"deleted": provider_id})


# --------------------------------------------------------------------------- #
# 知识库
# --------------------------------------------------------------------------- #
@bp.get("/worlds/<key>/knowledge")
def knowledge_list(key: str):
    with get_db().session() as session:
        world = get_world_by_key(session, key)
        return jsonify([d.to_dict() for d in list_docs(session, world.id)])


@bp.post("/worlds/<key>/knowledge")
def knowledge_upsert(key: str):
    payload = request.get_json(silent=True) or {}
    slug = (payload.get("slug") or "").strip()
    title = (payload.get("title") or "").strip()
    content = payload.get("content") or ""
    if not slug or not title:
        raise ValueError("slug 与 title 不能为空")
    if not content.strip():
        raise ValueError("content 不能为空")

    with get_db().session() as session:
        world = get_world_by_key(session, key)
        doc = upsert_doc(
            session,
            world,
            slug=slug,
            title=title,
            content=content,
            source=payload.get("source", ""),
            reliability=payload.get("reliability", "secondary"),
        )
        return jsonify(doc.to_dict()), 201


@bp.get("/worlds/<key>/knowledge/search")
def knowledge_search(key: str):
    query = request.args.get("q", "")
    limit = min(int(request.args.get("limit", 4)), 20)
    with get_db().session() as session:
        world = get_world_by_key(session, key)
        return jsonify(search(session, world.id, query, limit=limit))


# --------------------------------------------------------------------------- #
# 分析
# --------------------------------------------------------------------------- #
@bp.post("/branches/<int:branch_id>/analyze")
def analyze_route(branch_id: int):
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    event_id = payload.get("event_id")
    provider_id = payload.get("provider_id")
    model = payload.get("model")
    api_key = request.headers.get(KEY_HEADER, "").strip()

    with get_db().session() as session:
        branch = get_branch(session, branch_id)
        provider = get_provider(session, provider_id)
        result = analyze(
            session,
            branch,
            question=question,
            event_id=event_id,
            provider=provider,
            api_key=api_key,
            model=model,
        )
        return jsonify(result)


@bp.get("/branches/<int:branch_id>/material")
def material_route(branch_id: int):
    """不调用模型，只看会送给模型的材料（调试与自证用）。"""
    from ..ai import build_context, format_context

    event_id = request.args.get("event_id", type=int)
    question = request.args.get("q", "")
    with get_db().session() as session:
        branch = get_branch(session, branch_id)
        ctx = build_context(session, branch, question=question, event_id=event_id)
        return jsonify({"text": format_context(ctx), "citations": ctx["citation_list"]})