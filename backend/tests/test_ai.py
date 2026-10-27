"""知识库与 AI 分析层的测试。"""

from __future__ import annotations

import pytest

from app.ai import (
    LLMError,
    analyze,
    build_context,
    chunk_text,
    format_context,
    get_provider,
    search,
    upsert_doc,
)
from app.ai.providers import LLMConfig, MockClient, build_client
from app.models import LlmProvider
from app.seed import seed_knowledge
from app.services import create_branch, get_world_by_key


@pytest.fixture()
def tang(db_session):
    return get_world_by_key(db_session, "tang_750")


@pytest.fixture()
def branch(db_session):
    world = get_world_by_key(db_session, "tang_750")
    return create_branch(db_session, world, name="AI 测试", seed=3)


# --------------------------------------------------------------------------- #
# 切片与检索
# --------------------------------------------------------------------------- #
def test_chunk_text_splits_long_content():
    text = "\n\n".join("段落" * 100 for _ in range(5))
    chunks = chunk_text(text, size=120)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


def test_chunk_text_keeps_short_text_whole():
    assert chunk_text("很短的一段资料。") == ["很短的一段资料。"]


def test_upsert_doc_is_idempotent(db_session, tang):
    first = upsert_doc(
        db_session, tang, slug="t1", title="测试资料", content="甲" * 400, source="test"
    )
    second = upsert_doc(
        db_session, tang, slug="t1", title="测试资料改", content="乙" * 100, source="test"
    )
    assert first.id == second.id
    assert second.title == "测试资料改"
    assert len(second.chunks) == 1


def test_search_finds_relevant_chunk(db_session, tang):
    seed_knowledge(db_session)
    hits = search(db_session, tang.id, "粮价 赈济 常平仓", limit=3)
    assert hits, "应当能检索到赈济相关资料"
    assert any("赈济" in h["text"] or "常平仓" in h["text"] for h in hits)


def test_search_returns_empty_for_unrelated_query(db_session, tang):
    seed_knowledge(db_session)
    hits = search(db_session, tang.id, "量子力学与芯片制程", limit=3)
    assert hits == []


# --------------------------------------------------------------------------- #
# 材料组装
# --------------------------------------------------------------------------- #
def test_context_contains_facts_not_inventions(db_session, branch):
    ctx = build_context(db_session, branch)
    text = format_context(ctx)
    assert "各道现状" in text
    assert "河北道" in text
    assert "资料" in text or "参考资料" in text
    assert isinstance(ctx["regions"], list) and len(ctx["regions"]) <= 7


def test_context_includes_focus_event_and_chain(db_session, branch):
    from app.services import apply_action

    shock = apply_action(db_session, branch, "shock", "hebei", {"damage_ratio": 0.8})
    db_session.flush()
    ctx = build_context(db_session, branch, event_id=shock.id)
    text = format_context(ctx)
    assert "重点事件" in text
    assert shock.title in text


def test_context_includes_military_and_court(db_session):
    """AI 材料里应当能看到兵力、忠诚、待决事项与史实对照。"""
    from app.engine import SimulationEngine
    from app.services import create_branch, get_world_by_key

    world = get_world_by_key(db_session, "tang_755")
    if world is None:
        from app.seed import anlushan_755

        world = anlushan_755.seed(db_session)
        db_session.flush()

    branch = create_branch(db_session, world, name="AI材料", seed=5)
    SimulationEngine(db_session).advance(branch, months=8)

    ctx = build_context(db_session, branch, question="潼关守得住吗")
    text = format_context(ctx)

    assert ctx["army_lines"], "应列出各军"
    assert "战力" in text
    assert "【各军】" in text
    assert "【人物忠诚】" in text
    assert "【史实对照】" in text


def test_system_prompt_marks_derived_data():
    from app.ai.context import SYSTEM_PROMPT

    assert "不是史料原文" in SYSTEM_PROMPT
    assert "已改道" in SYSTEM_PROMPT


def test_context_rejects_foreign_event(db_session, branch):
    with pytest.raises(LookupError):
        build_context(db_session, branch, event_id=999999)


# --------------------------------------------------------------------------- #
# 适配器
# --------------------------------------------------------------------------- #
def test_build_client_unknown_kind():
    with pytest.raises(LLMError):
        build_client(LLMConfig(kind="does-not-exist"))


def test_openai_adapter_requires_key():
    from app.ai.providers import OpenAICompatibleClient

    client = OpenAICompatibleClient(
        LLMConfig(kind="openai_compatible", base_url="https://example.com/v1", model="m")
    )
    with pytest.raises(LLMError) as err:
        client.chat([{"role": "user", "content": "hi"}])
    assert "API Key" in str(err.value)


def test_mock_client_is_deterministic():
    client = MockClient(LLMConfig(kind="mock"))
    a = client.chat([{"role": "user", "content": "测试材料"}])
    b = client.chat([{"role": "user", "content": "测试材料"}])
    assert a == b
    assert "离线" in a


# --------------------------------------------------------------------------- #
# 端到端（离线适配器）
# --------------------------------------------------------------------------- #
def _mock_provider(session) -> LlmProvider:
    row = LlmProvider(
        name="离线测试",
        kind="mock",
        base_url="",
        model="mock-model",
        enabled=True,
        is_default=True,
    )
    session.add(row)
    session.flush()
    return row


def test_analyze_with_mock_provider(db_session, branch):
    seed_knowledge(db_session)
    provider = _mock_provider(db_session)

    result = analyze(
        db_session,
        branch,
        question="当前最值得关注的风险是什么？",
        provider=provider,
        api_key="",
    )
    assert result["answer"]
    assert result["provider"]["kind"] == "mock"
    assert result["context"]["region_count"] == 7
    assert "material_preview" in result
    # 材料里不能出现任何 Key
    assert "sk-" not in result["material_preview"]


def test_analyze_without_provider_raises(db_session, branch):
    from app.ai import ProviderNotConfigured

    with pytest.raises(ProviderNotConfigured):
        analyze(db_session, branch, question="你好", provider=None, api_key="")


def test_provider_lookup_prefers_default(db_session):
    _mock_provider(db_session)
    found = get_provider(db_session)
    assert found is not None and found.kind == "mock"


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def test_ai_api_flow(client):
    branch = client.post("/api/worlds/tang_750/branches", json={"seed": 3}).get_json()
    bid = branch["id"]

    # 配置一个离线 provider
    created = client.post(
        "/api/ai/providers",
        json={"name": "离线", "kind": "mock", "base_url": "", "model": "mock", "is_default": True},
    )
    assert created.status_code == 201
    assert "api_key" not in created.get_json()

    material = client.get(f"/api/ai/branches/{bid}/material")
    assert material.status_code == 200
    assert "各道现状" in material.get_json()["text"]

    resp = client.post(
        f"/api/ai/branches/{bid}/analyze",
        json={"question": "分析当前局势"},
        headers={"X-LLM-Key": "sk-should-not-leak"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["answer"]
    assert "sk-should-not-leak" not in str(body)


def test_ai_api_without_provider_returns_400(client):
    branch = client.post("/api/worlds/tang_750/branches", json={}).get_json()
    resp = client.post(f"/api/ai/branches/{branch['id']}/analyze", json={"question": "hi"})
    assert resp.status_code == 400
    assert "配置" in resp.get_json()["error"]


def test_knowledge_api(client):
    assert client.get("/api/ai/worlds/tang_750/knowledge").status_code == 200

    created = client.post(
        "/api/ai/worlds/tang_750/knowledge",
        json={
            "slug": "test-doc",
            "title": "测试资料",
            "content": "这是一段关于唐代粮价的测试资料，用于验证入库与检索。",
            "source": "测试",
            "reliability": "assumption",
        },
    )
    assert created.status_code == 201
    assert created.get_json()["title"] == "测试资料"

    hits = client.get("/api/ai/worlds/tang_750/knowledge/search?q=粮价").get_json()
    assert any("粮价" in h["text"] for h in hits)


def test_provider_api_rejects_bad_kind(client):
    resp = client.post("/api/ai/providers", json={"name": "x", "kind": "nope"})
    assert resp.status_code == 400