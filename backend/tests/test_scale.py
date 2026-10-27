"""多尺度观察的测试。"""

from __future__ import annotations

import pytest

from app.services import aggregate_by_scale, create_branch, get_world_by_key


def _branch(session):
    world = get_world_by_key(session, "tang_750")
    return create_branch(session, world, name="尺度测试", seed=3)


def test_world_scale_aggregates_by_faction(db_session):
    branch = _branch(db_session)
    view = aggregate_by_scale(db_session, branch, "world")

    assert view["scale"] == "world"
    units = view["units"]
    assert len(units) == 2, "唐朝世界有两个势力"
    assert {u["kind"] for u in units} == {"faction"}
    assert view["event_scopes"] == ["world", "nation"]

    total_regions = sum(u["metrics"]["region_count"] for u in units)
    assert total_regions == 7, "聚合不能丢地区"


def test_region_scale_returns_each_region(db_session):
    branch = _branch(db_session)
    view = aggregate_by_scale(db_session, branch, "region")

    assert len(view["units"]) == 7
    assert all(u["kind"] == "region" for u in view["units"])
    assert view["event_scopes"] == ["region"]


def test_aggregation_preserves_totals(db_session):
    """聚合只换视角，不能凭空创造或丢失数据。"""
    branch = _branch(db_session)
    region_view = aggregate_by_scale(db_session, branch, "region")
    world_view = aggregate_by_scale(db_session, branch, "world")

    region_pop = sum(u["metrics"]["population"] for u in region_view["units"])
    world_pop = sum(u["metrics"]["population"] for u in world_view["units"])
    assert region_pop == world_pop

    region_grain = sum(u["metrics"]["grain_stock"] for u in region_view["units"])
    world_grain = sum(u["metrics"]["grain_stock"] for u in world_view["units"])
    assert region_grain == pytest.approx(world_grain, rel=1e-6)


def test_local_scale_includes_local_events(db_session):
    branch = _branch(db_session)
    view = aggregate_by_scale(db_session, branch, "local")
    assert "local" in view["event_scopes"]
    assert len(view["units"]) == 7


def test_unknown_scale_rejected(db_session):
    branch = _branch(db_session)
    with pytest.raises(ValueError):
        aggregate_by_scale(db_session, branch, "galaxy")


def test_view_api(client):
    branch = client.post("/api/worlds/tang_750/branches", json={"seed": 3}).get_json()
    bid = branch["id"]

    resp = client.get(f"/api/branches/{bid}/view?scale=world")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["scale"] == "world"
    assert len(body["units"]) == 2

    resp = client.get(f"/api/branches/{bid}/view?scale=region")
    assert len(resp.get_json()["units"]) == 7

    assert client.get(f"/api/branches/{bid}/view?scale=galaxy").status_code == 400