async def test_set_upgraded_kind_is_configurable(authed_admin_client):
    r = await authed_admin_client.put(
        "/api/me/notification-preferences/set_upgraded", json={"channel": "in_app"})
    assert r.status_code == 200
    assert r.json()["kind"] == "set_upgraded" and r.json()["channel"] == "in_app"
    listed = await authed_admin_client.get("/api/me/notification-preferences")
    item = {"kind": "set_upgraded", "channel": "in_app", "connector_id": None}
    assert item in listed.json()["items"]


async def test_unknown_kind_is_rejected(authed_admin_client):
    r = await authed_admin_client.put(
        "/api/me/notification-preferences/bogus", json={"channel": "email"})
    assert r.status_code == 400
