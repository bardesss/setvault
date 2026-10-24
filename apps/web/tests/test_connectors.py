import json
import uuid

from setvault_core.db import session_factory
from setvault_core.models.identity import User
from setvault_core.models.system import AuditEvent, NotificationConnector
from setvault_core.services.crypto import Crypter
from setvault_core.services.passwords import hash_password
from setvault_web.config import get_settings
from sqlalchemy import select


async def test_create_smtp_connector_and_round_trip_secret(authed_admin_client):
    response = await authed_admin_client.post("/api/connectors", json={
        "kind": "smtp", "name": "default",
        "config": {
            "host": "smtp.example.test", "port": 587, "encryption": "starttls",
            "username": "noreply", "password": "shhh-secret",
            "from_email": "noreply@setvault.test", "from_name": "SetVault",
            "reply_to": None,
        },
        "scope_filter": {"kinds": ["*"]},
        "enabled": True,
    })
    assert response.status_code == 201
    cid = response.json()["id"]
    # GET must not echo the plaintext password
    show = await authed_admin_client.get(f"/api/connectors/{cid}")
    assert show.status_code == 200
    body = show.json()
    assert body["config"]["host"] == "smtp.example.test"
    assert "password" not in body["config"]
    assert body["config"]["password_set"] is True


async def test_test_send_uses_dry_run_in_tests(authed_admin_client):
    create = await authed_admin_client.post("/api/connectors", json={
        "kind": "smtp", "name": "default",
        "config": {"host": "smtp.example.test", "port": 25, "encryption": "none",
                   "username": None, "password": None,
                   "from_email": "n@x.test", "from_name": "X", "reply_to": None},
        "scope_filter": {"kinds": ["*"]}, "enabled": True,
    })
    cid = create.json()["id"]
    response = await authed_admin_client.post(f"/api/connectors/{cid}/test-send",
                                              json={"to": "rcpt@example.test", "dry_run": True})
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["dry_run"] is True


# --------------------------------------------------------------------------- #
# P2a A6: PATCH / DELETE
# --------------------------------------------------------------------------- #

def _smtp(**over):
    cfg = {"host": "smtp.example.test", "port": 587, "encryption": "starttls",
           "username": "noreply", "password": "shhh-secret",
           "from_email": "noreply@setvault.test", "from_name": "SetVault",
           "reply_to": None}
    cfg.update(over)
    return {"kind": "smtp", "name": "default", "config": cfg,
            "scope_filter": {"kinds": ["*"]}, "enabled": True}


async def _stored_config(cid):
    crypter = Crypter(get_settings().secret_key)
    async with session_factory()() as s:
        row = await s.get(NotificationConnector, uuid.UUID(cid))
        return json.loads(crypter.decrypt(row.encrypted_config).decode("utf-8"))


async def _audit(action):
    async with session_factory()() as s:
        return (await s.execute(
            select(AuditEvent).where(AuditEvent.action == action)
        )).scalars().all()


async def test_patch_keeps_password_when_blank(authed_admin_client):
    c = authed_admin_client
    cid = (await c.post("/api/connectors", json=_smtp())).json()["id"]
    r = await c.patch(f"/api/connectors/{cid}", json={"config": {"password": ""}})
    assert r.status_code == 200
    assert r.json()["config"]["password_set"] is True
    r = await c.patch(f"/api/connectors/{cid}", json={"config": {"host": "h2.example.test"}})
    assert r.json()["config"]["password_set"] is True
    assert (await _stored_config(cid))["password"] == "shhh-secret"
    # a new password replaces it
    await c.patch(f"/api/connectors/{cid}", json={"config": {"password": "new-secret"}})
    assert (await _stored_config(cid))["password"] == "new-secret"
    # explicit null clears it
    r = await c.patch(f"/api/connectors/{cid}", json={"config": {"password": None}})
    assert r.json()["config"]["password_set"] is False
    assert not (await _stored_config(cid)).get("password")


async def test_patch_changes_host_and_audits_without_secret(authed_admin_client):
    c = authed_admin_client
    cid = (await c.post("/api/connectors", json=_smtp())).json()["id"]
    r = await c.patch(f"/api/connectors/{cid}", json={
        "name": "renamed", "enabled": False,
        "config": {"host": "mail.example.test", "port": 465, "password": "rotated-secret"},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "renamed" and body["enabled"] is False
    assert body["config"]["host"] == "mail.example.test"
    assert body["config"]["port"] == 465
    assert body["config"]["username"] == "noreply"  # untouched
    assert "password" not in body["config"]

    rows = await _audit("connector.edited")
    assert len(rows) == 1
    assert rows[0].target_id == cid
    assert rows[0].before == {
        "name": "default", "enabled": True,
        "config": {"host": "smtp.example.test", "port": 587, "password_set": True},
    }
    assert rows[0].after == {
        "name": "renamed", "enabled": False,
        "config": {"host": "mail.example.test", "port": 465, "password_set": True},
    }
    dumped = json.dumps([rows[0].before, rows[0].after])
    assert "shhh-secret" not in dumped and "rotated-secret" not in dumped


async def test_patch_validates_and_404s(authed_admin_client):
    c = authed_admin_client
    cid = (await c.post("/api/connectors", json=_smtp())).json()["id"]
    assert (await c.patch(f"/api/connectors/{cid}",
                          json={"config": {"port": 0}})).status_code == 422
    assert (await c.patch(f"/api/connectors/{cid}",
                          json={"config": {"from_email": "nope"}})).status_code == 422
    assert (await c.patch("/api/connectors/not-a-uuid", json={"name": "x"})).status_code == 404
    assert (await c.delete("/api/connectors/not-a-uuid")).status_code == 404
    missing = str(uuid.uuid4())
    assert (await c.patch(f"/api/connectors/{missing}", json={"name": "x"})).status_code == 404


async def test_delete_connector(authed_admin_client):
    c = authed_admin_client
    cid = (await c.post("/api/connectors", json=_smtp())).json()["id"]
    r = await c.delete(f"/api/connectors/{cid}")
    assert r.status_code == 204
    assert (await c.get(f"/api/connectors/{cid}")).status_code == 404
    assert (await c.delete(f"/api/connectors/{cid}")).status_code == 404
    rows = await _audit("connector.deleted")
    assert len(rows) == 1 and rows[0].target_id == cid
    assert rows[0].before == {"kind": "smtp", "name": "default"}


async def test_non_admin_403(client, seeded_admin):
    async with session_factory()() as s:
        s.add(User(email="member-conn@x.test", username="member-conn", display_name="M",
                   password_hash=hash_password("hunter2hunter2"), role="member"))
        await s.commit()
    login = await client.post("/api/auth/login", json={
        "email": "member-conn@x.test", "password": "hunter2hunter2"})
    assert login.status_code == 200
    client.cookies = login.cookies
    client.headers["X-CSRF-Token"] = login.cookies["csrf_token"]
    fake = "00000000-0000-0000-0000-000000000001"
    assert (await client.patch(f"/api/connectors/{fake}", json={"name": "x"})).status_code == 403
    assert (await client.delete(f"/api/connectors/{fake}")).status_code == 403
