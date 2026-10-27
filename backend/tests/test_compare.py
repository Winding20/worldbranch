"""分支对比的测试。"""

from __future__ import annotations

import pytest

from app.engine import SimulationEngine
from app.services import compare_branches, create_branch, fork_branch, get_world_by_key


def _branch(session, seed: int = 3):
    world = get_world_by_key(session, "tang_750")
    return create_branch(session, world, name="对比分支", seed=seed)


def test_compare_same_branch_reports_no_divergence(db_session):
    branch = _branch(db_session)
    result = compare_branches(db_session, branch, branch)

    assert result["divergence"]["same_branch"] is True
    assert result["events"]["left_only"] == []
    assert result["events"]["right_only"] == []
    for row in result["regions"]:
        for metric, delta in row["delta"].items():
            assert delta == 0, f"{row['name']} 的 {metric} 不应有差异"


def test_compare_after_divergence_shows_differences(db_session):
    source = _branch(db_session, seed=7)
    engine = SimulationEngine(db_session)
    engine.advance(source, months=6)

    fork = fork_branch(db_session, source, name="对照分支")
    # 只在源分支上再推进，两条线就此分开
    engine.advance(source, months=6)

    result = compare_branches(db_session, source, fork)
    div = result["divergence"]
    assert div["same_branch"] is False
    assert div["left_ancestor_of_right"] is True, "fork 是从 source 派生的，source 是它的祖先"
    assert div["common_ancestor_id"] == source.id

    # 时间不同，状态必然不同
    changed = [r for r in result["regions"] if r["delta"]["grain_stock"] != 0]
    assert changed, "推进更多月份后存粮应当出现差异"

    # 源分支多推进 6 个月，独有事件应当比派生分支多
    assert len(result["events"]["left_only"]) >= len(result["events"]["right_only"])


def test_compare_rejects_cross_world(db_session):
    branch = _branch(db_session)
    world = get_world_by_key(db_session, "tang_750")
    other = create_branch(db_session, world, name="同世界另一条")
    # 同世界应允许
    compare_branches(db_session, branch, other)


def test_compare_api(client):
    created = client.post("/api/worlds/tang_750/branches", json={"seed": 5}).get_json()
    left_id = created["id"]
    client.post(f"/api/branches/{left_id}/advance", json={"months": 4})
    fork = client.post(f"/api/branches/{left_id}/fork", json={"name": "对照"}).get_json()
    client.post(f"/api/branches/{left_id}/advance", json={"months": 4})

    resp = client.get(f"/api/branches/compare?left={left_id}&right={fork['id']}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["left"]["id"] == left_id
    assert body["right"]["id"] == fork["id"]
    assert len(body["regions"]) == 7
    assert "left_only" in body["events"]


def test_compare_api_requires_both_ids(client):
    resp = client.get("/api/branches/compare?left=1")
    assert resp.status_code == 400


def test_compare_api_unknown_branch(client):
    resp = client.get("/api/branches/compare?left=1&right=99999")
    assert resp.status_code == 404