"""API 层测试。"""

from __future__ import annotations


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_list_worlds(client):
    resp = client.get("/api/worlds")
    assert resp.status_code == 200
    data = resp.get_json()
    assert any(w["key"] == "tang_750" for w in data)


def test_world_detail_has_regions_and_geo(client):
    resp = client.get("/api/worlds/tang_750")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["regions"]) == 7
    region = data["regions"][0]
    # 地理轮廓由现代省界近似拼成，因此是 MultiPolygon
    assert region["geo"]["type"] == "MultiPolygon"
    assert region["geo"]["coordinates"], "几何数据不应为空"
    assert region["data_quality"]["population"] == "estimate"
    assert region["data_quality"]["geo"] == "approximate"


def test_world_not_found(client):
    resp = client.get("/api/worlds/not-exist")
    assert resp.status_code == 404
    assert "不存在" in resp.get_json()["error"]


def test_create_branch_and_advance(client):
    created = client.post("/api/worlds/tang_750/branches", json={"precision": "standard", "seed": 1})
    assert created.status_code == 201
    branch = created.get_json()
    branch_id = branch["id"]

    advanced = client.post(f"/api/branches/{branch_id}/advance", json={"months": 6})
    assert advanced.status_code == 200
    report = advanced.get_json()
    assert report["months"] == 6
    assert report["to_date"] == "750-07-01"
    assert len(report["region_states"]) == 7

    state = client.get(f"/api/branches/{branch_id}/state")
    assert state.status_code == 200
    body = state.get_json()
    assert body["branch"]["tick_index"] == 6
    assert any(r["geo"] for r in body["regions"])


def test_events_endpoint_filters_by_scope(client):
    branch = client.post("/api/worlds/tang_750/branches", json={"seed": 3}).get_json()
    branch_id = branch["id"]
    client.post(f"/api/branches/{branch_id}/advance", json={"months": 24})

    all_events = client.get(f"/api/branches/{branch_id}/events").get_json()
    assert all_events

    macro_only = client.get(
        f"/api/branches/{branch_id}/events?min_scope=world"
    ).get_json()
    assert len(macro_only) <= len(all_events)
    assert all(e["scope"] == "world" for e in macro_only)


def test_fork_endpoint(client):
    branch = client.post("/api/worlds/tang_750/branches", json={"seed": 2}).get_json()
    branch_id = branch["id"]
    client.post(f"/api/branches/{branch_id}/advance", json={"months": 3})

    forked = client.post(f"/api/branches/{branch_id}/fork", json={"name": "分支A"})
    assert forked.status_code == 201
    fork = forked.get_json()
    assert fork["parent_branch_id"] == branch_id
    assert fork["current_date"] == "750-04-01"


def test_event_chain_endpoint(client):
    branch = client.post("/api/worlds/tang_750/branches", json={"seed": 3}).get_json()
    branch_id = branch["id"]
    client.post(f"/api/branches/{branch_id}/advance", json={"months": 24})

    events = client.get(f"/api/branches/{branch_id}/events?limit=5").get_json()
    assert events
    event_id = events[0]["id"]

    chain = client.get(f"/api/branches/{branch_id}/events/{event_id}/chain")
    assert chain.status_code == 200
    body = chain.get_json()
    assert body["root_id"] == event_id
    assert any(node["id"] == event_id for node in body["nodes"])


def test_event_chain_unknown_event(client):
    branch = client.post("/api/worlds/tang_750/branches", json={}).get_json()
    resp = client.get(f"/api/branches/{branch['id']}/events/999999/chain")
    assert resp.status_code == 404


def test_advance_rejects_bad_input(client):
    branch = client.post("/api/worlds/tang_750/branches", json={}).get_json()
    branch_id = branch["id"]
    assert client.post(f"/api/branches/{branch_id}/advance", json={"months": 0}).status_code == 400
    assert (
        client.post(
            f"/api/branches/{branch_id}/advance",
            json={"months": 1, "precision": "ultra"},
        ).status_code
        == 400
    )


def test_index_page_served(client):
    """根路径：前端已构建则重定向到 /app/，未构建则明确说明。"""
    resp = client.get("/")
    assert resp.status_code in (200, 302)
    if resp.status_code == 200:
        # 未构建时给出可操作的提示，而不是空白页
        assert "构建" in resp.get_data(as_text=True)
    else:
        assert resp.headers["Location"].endswith("/app/")


def test_legacy_page_removed(client):
    """旧版静态界面已移除，不应再对外提供。"""
    assert client.get("/legacy").status_code == 404


def test_vue_app_is_served(client):
    """Vue 版构建产物应当挂在 /app/ 下。"""
    resp = client.get("/app/")
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        body = resp.get_data(as_text=True)
        assert '<div id="app">' in body
        assert "/app/assets/" in body