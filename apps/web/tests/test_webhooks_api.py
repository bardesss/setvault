import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from setvault_core.db import session_factory
from setvault_core.models.identity import User
from setvault_core.models.library_webhook import LibraryWebhook, WebhookDelivery
from setvault_core.models.system import AuditEvent
from setvault_core.services.crypto import Crypter
from setvault_core.services.passwords import hash_password
from setvault_core.services.webhook_security import get_headers, get_secret
from setvault_web.config import get_settings
from sqlalchemy import select

URL = "https://hooks.example.test/in"


async def _create(client, **over):
    body = {"name": "w", "target_url": URL, "events": ["set.published"]} | over
    return await client.post("/api/admin/webhooks", json=body)


async def _stored_headers(wh_id):
    crypter = Crypter(get_settings().secret_key)
    async with session_factory()() as s:
        row = await s.get(LibraryWebhook, uuid.UUID(wh_id))
        return get_headers(row, crypter)


async def _audit(action):
    async with session_factory()() as s:
        return (await s.execute(
            select(AuditEvent).where(AuditEvent.action == action)
        )).scalars().all()


async def test_create_returns_secret_once(authed_admin_client):
    r = await _create(authed_admin_client, headers={"X-Token": "hunter-value"})
    assert r.status_code == 201
    body = r.json()
    assert body["secret"] and body["secret_set"] is True
    assert "headers" not in body
    assert body["header_names"] == ["X-Token"]
    items = (await authed_admin_client.get("/api/admin/webhooks")).json()["items"]
    assert len(items) == 1
    assert "secret" not in items[0]
    assert items[0]["secret_set"] is True
    assert await _stored_headers(body["id"]) == {"X-Token": "hunter-value"}


async def test_rotate_secret_changes_it_and_audits(authed_admin_client):
    created = (await _create(authed_admin_client)).json()
    r = await authed_admin_client.post(f"/api/admin/webhooks/{created['id']}/rotate-secret")
    assert r.status_code == 200
    new = r.json()["secret"]
    assert new and new != created["secret"]
    async with session_factory()() as s:
        row = await s.get(LibraryWebhook, uuid.UUID(created["id"]))
        assert get_secret(row, Crypter(get_settings().secret_key)) == new
    rows = await _audit("webhook.secret_rotated")
    assert len(rows) == 1 and rows[0].target_id == created["id"]
    assert new not in json.dumps(rows[0].after or {})


async def test_list_never_returns_header_values(authed_admin_client):
    await _create(authed_admin_client, headers={"X-A": "value-one-zzz", "X-B": "value-two-zzz"})
    r = await authed_admin_client.get("/api/admin/webhooks")
    assert "zzz" not in r.text
    assert r.json()["items"][0]["header_names"] == ["X-A", "X-B"]


async def test_list_masks_legacy_headers(authed_admin_client):
    async with session_factory()() as s:
        s.add(LibraryWebhook(name="old", target_url=URL, events=[], headers={"A": "1"}))
        await s.commit()
    items = (await authed_admin_client.get("/api/admin/webhooks")).json()["items"]
    assert items[0]["header_names"] == ["A"]
    assert "headers" not in items[0]
    assert '"1"' not in json.dumps(items)


async def test_patch_keeps_omitted_header_values(authed_admin_client):
    wh = (await _create(authed_admin_client, headers={"A": "1", "B": "2"})).json()
    r = await authed_admin_client.patch(
        f"/api/admin/webhooks/{wh['id']}", json={"name": "x", "headers": {"B": "3"}},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "x"
    assert await _stored_headers(wh["id"]) == {"A": "1", "B": "3"}


async def test_patch_without_headers_changes_nothing(authed_admin_client):
    wh = (await _create(authed_admin_client, headers={"A": "1"})).json()
    r = await authed_admin_client.patch(f"/api/admin/webhooks/{wh['id']}", json={"name": "y"})
    assert r.status_code == 200
    assert await _stored_headers(wh["id"]) == {"A": "1"}


async def test_patch_migrates_legacy_headers_and_keeps_omitted(authed_admin_client):
    async with session_factory()() as s:
        row = LibraryWebhook(name="old", target_url=URL, events=[], headers={"A": "1", "B": "2"})
        s.add(row)
        await s.commit()
        wid = str(row.id)
    r = await authed_admin_client.patch(f"/api/admin/webhooks/{wid}", json={"headers": {"B": "3"}})
    assert r.status_code == 200
    assert await _stored_headers(wid) == {"A": "1", "B": "3"}


@pytest.mark.parametrize("empty", ["", None])
async def test_patch_deletes_header_with_empty_value(authed_admin_client, empty):
    wh = (await _create(authed_admin_client, headers={"A": "1", "B": "2"})).json()
    r = await authed_admin_client.patch(
        f"/api/admin/webhooks/{wh['id']}", json={"headers": {"A": empty}},
    )
    assert r.status_code == 200
    assert r.json()["header_names"] == ["B"]
    assert await _stored_headers(wh["id"]) == {"B": "2"}


async def test_patch_audit_lists_field_names_only(authed_admin_client):
    wh = (await _create(authed_admin_client)).json()
    await authed_admin_client.patch(
        f"/api/admin/webhooks/{wh['id']}", json={"name": "n", "headers": {"A": "secret-val"}},
    )
    rows = await _audit("webhook.updated")
    assert len(rows) == 1
    assert sorted(rows[0].after["fields"]) == ["headers", "name"]
    assert "secret-val" not in json.dumps(rows[0].after)


async def test_rejects_unknown_event(authed_admin_client):
    r = await _create(authed_admin_client, events=["set.published", "set.exploded"])
    assert r.status_code == 400
    r = await _create(authed_admin_client, events=["webhook.test"])
    assert r.status_code == 400
    wh = (await _create(authed_admin_client)).json()
    r = await authed_admin_client.patch(
        f"/api/admin/webhooks/{wh['id']}", json={"events": ["nope"]},
    )
    assert r.status_code == 400


@pytest.mark.parametrize("url", ["ftp://x", "javascript:alert(1)", "not a url"])
async def test_rejects_non_http_url(authed_admin_client, url):
    assert (await _create(authed_admin_client, target_url=url)).status_code == 400
    wh = (await _create(authed_admin_client)).json()
    r = await authed_admin_client.patch(
        f"/api/admin/webhooks/{wh['id']}", json={"target_url": url},
    )
    assert r.status_code == 400


async def test_rejects_bad_header_name(authed_admin_client):
    assert (await _create(authed_admin_client, headers={"bad name": "v"})).status_code == 400
    assert (await _create(authed_admin_client, headers={"x" * 65: "v"})).status_code == 400
    wh = (await _create(authed_admin_client)).json()
    r = await authed_admin_client.patch(
        f"/api/admin/webhooks/{wh['id']}", json={"headers": {"a:b": "v"}},
    )
    assert r.status_code == 400


async def test_deliveries_listed_newest_first(authed_admin_client):
    wh = (await _create(authed_admin_client)).json()
    now = datetime.now(UTC)
    async with session_factory()() as s:
        for i in range(55):
            s.add(WebhookDelivery(
                webhook_id=uuid.UUID(wh["id"]), delivery_id=f"d{i}", event="set.published",
                attempt=1, status_code=200, created_at=now - timedelta(minutes=100 - i),
            ))
        await s.commit()
    r = await authed_admin_client.get(f"/api/admin/webhooks/{wh['id']}/deliveries")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 50
    assert items[0]["delivery_id"] == "d54"
    assert set(items[0]) == {
        "delivery_id", "event", "attempt", "status_code", "error", "duration_ms", "created_at",
    }
    stamps = [i["created_at"] for i in items]
    assert stamps == sorted(stamps, reverse=True)


async def test_deliveries_unknown_webhook_404(authed_admin_client):
    r = await authed_admin_client.get(f"/api/admin/webhooks/{uuid.uuid4()}/deliveries")
    assert r.status_code == 404


async def test_non_admin_gets_403(client, seeded_admin):
    async with session_factory()() as s:
        s.add(User(email="member-wh@x.test", username="member-wh", display_name="M",
                   password_hash=hash_password("hunter2hunter2"), role="member"))
        await s.commit()
    login = await client.post("/api/auth/login", json={
        "email": "member-wh@x.test", "password": "hunter2hunter2"})
    assert login.status_code == 200
    client.cookies = login.cookies
    client.headers["X-CSRF-Token"] = login.cookies["csrf_token"]
    base = "/api/admin/webhooks"
    fake = "00000000-0000-0000-0000-000000000001"
    calls = [
        client.get(base),
        client.post(base, json={"name": "a", "target_url": URL}),
        client.patch(f"{base}/{fake}", json={"name": "x"}),
        client.delete(f"{base}/{fake}"),
        client.post(f"{base}/{fake}/test"),
        client.post(f"{base}/{fake}/rotate-secret"),
        client.get(f"{base}/{fake}/deliveries"),
    ]
    for coro in calls:
        assert (await coro).status_code == 403


async def test_bad_uuid_is_404(authed_admin_client):
    base = "/api/admin/webhooks/not-a-uuid"
    assert (await authed_admin_client.patch(base, json={"name": "x"})).status_code == 404
    assert (await authed_admin_client.delete(base)).status_code == 404
    assert (await authed_admin_client.post(f"{base}/test")).status_code == 404
    assert (await authed_admin_client.post(f"{base}/rotate-secret")).status_code == 404
    assert (await authed_admin_client.get(f"{base}/deliveries")).status_code == 404


async def test_test_button_does_not_retry(authed_admin_client, monkeypatch):
    wh = (await _create(authed_admin_client)).json()
    seen = {}

    def fake(queue, **kw):
        seen.update(kw)
        return "did-1"

    monkeypatch.setattr("setvault_web.api.webhooks.enqueue_dispatch", fake)
    r = await authed_admin_client.post(f"/api/admin/webhooks/{wh['id']}/test")
    assert r.status_code == 200
    assert r.json() == {"status": "queued", "delivery_id": "did-1"}
    assert seen["retry"] is False and seen["event"] == "webhook.test"


@pytest.mark.parametrize("field", ["name", "target_url", "events", "enabled"])
async def test_patch_rejects_explicit_null(authed_admin_client, field):
    wh = (await _create(authed_admin_client)).json()
    r = await authed_admin_client.patch(f"/api/admin/webhooks/{wh['id']}", json={field: None})
    assert r.status_code == 400
    assert field in r.json()["detail"]


async def test_patch_null_body_template_clears_and_null_headers_is_noop(authed_admin_client):
    wh = (await _create(
        authed_admin_client, body_template={"a": "b"}, headers={"A": "1"})).json()
    r = await authed_admin_client.patch(
        f"/api/admin/webhooks/{wh['id']}", json={"body_template": None, "headers": None})
    assert r.status_code == 200
    assert r.json()["body_template"] is None
    assert await _stored_headers(wh["id"]) == {"A": "1"}


@pytest.mark.parametrize("name", [
    "x-setvault-signature", "X-SetVault-Event", "Host", "content-length",
    "Transfer-Encoding", "CONNECTION",
])
async def test_rejects_reserved_header_names(authed_admin_client, name):
    assert (await _create(authed_admin_client, headers={name: "v"})).status_code == 400
    wh = (await _create(authed_admin_client)).json()
    r = await authed_admin_client.patch(
        f"/api/admin/webhooks/{wh['id']}", json={"headers": {name: "v"}})
    assert r.status_code == 400


async def test_rejects_case_insensitive_duplicate_header_names(authed_admin_client):
    assert (await _create(
        authed_admin_client, headers={"X-A": "1", "x-a": "2"})).status_code == 400
    wh = (await _create(authed_admin_client)).json()
    r = await authed_admin_client.patch(
        f"/api/admin/webhooks/{wh['id']}", json={"headers": {"X-A": "1", "x-a": "2"}})
    assert r.status_code == 400


@pytest.mark.parametrize("value", ["a\r\nX-Evil: 1", "a\nb", "a\rb", "a\x00b", "a\x7fb"])
async def test_rejects_control_chars_in_header_values(authed_admin_client, value):
    assert (await _create(authed_admin_client, headers={"X-A": value})).status_code == 400
    wh = (await _create(authed_admin_client)).json()
    r = await authed_admin_client.patch(
        f"/api/admin/webhooks/{wh['id']}", json={"headers": {"X-A": value}})
    assert r.status_code == 400


async def test_patch_matches_stored_header_names_case_insensitively(authed_admin_client):
    wh = (await _create(
        authed_admin_client, headers={"X-Plex-Token": "old", "X-B": "b"})).json()
    r = await authed_admin_client.patch(
        f"/api/admin/webhooks/{wh['id']}", json={"headers": {"x-plex-token": "new"}})
    assert r.status_code == 200
    assert await _stored_headers(wh["id"]) == {"X-Plex-Token": "new", "X-B": "b"}
    r = await authed_admin_client.patch(
        f"/api/admin/webhooks/{wh['id']}", json={"headers": {"X-PLEX-TOKEN": ""}})
    assert r.status_code == 200
    assert await _stored_headers(wh["id"]) == {"X-B": "b"}


async def _row_with_foreign_key(make_cols):
    other = Crypter("another-secret-key-0123456789")
    async with session_factory()() as s:
        row = LibraryWebhook(name="foreign", target_url=URL, events=[], **make_cols(other))
        s.add(row)
        await s.commit()
        return str(row.id)


async def test_list_tolerates_undecryptable_data(authed_admin_client):
    wid = await _row_with_foreign_key(lambda c: {
        "encrypted_headers": c.encrypt(b'{"A":"1"}'),
        "encrypted_secret": c.encrypt(b"s"),
    })
    r = await authed_admin_client.get("/api/admin/webhooks")
    assert r.status_code == 200
    (item,) = [i for i in r.json()["items"] if i["id"] == wid]
    assert item["header_names"] == []
    assert item["headers_unreadable"] is True
    assert item["secret_set"] is True


async def test_readable_row_is_not_flagged_unreadable(authed_admin_client):
    wh = (await _create(authed_admin_client, headers={"A": "1"})).json()
    assert wh["headers_unreadable"] is False


async def test_patch_headers_on_undecryptable_row_starts_fresh(authed_admin_client):
    wid = await _row_with_foreign_key(lambda c: {"encrypted_headers": c.encrypt(b'{"A":"1"}')})
    r = await authed_admin_client.patch(
        f"/api/admin/webhooks/{wid}", json={"headers": {"B": "2"}})
    assert r.status_code == 200
    assert r.json()["headers_unreadable"] is False
    assert await _stored_headers(wid) == {"B": "2"}


async def test_deliveries_tie_break_on_id(authed_admin_client):
    wh = (await _create(authed_admin_client)).json()
    same = datetime.now(UTC)
    async with session_factory()() as s:
        for i in range(3):
            s.add(WebhookDelivery(
                webhook_id=uuid.UUID(wh["id"]), delivery_id=f"t{i}", event="set.published",
                attempt=1, status_code=200, created_at=same))
        await s.commit()
        ids = (await s.execute(
            select(WebhookDelivery.delivery_id, WebhookDelivery.id)
            .where(WebhookDelivery.webhook_id == uuid.UUID(wh["id"]))
            .order_by(WebhookDelivery.id.desc()))).all()
    r = await authed_admin_client.get(f"/api/admin/webhooks/{wh['id']}/deliveries")
    assert [i["delivery_id"] for i in r.json()["items"]] == [d for d, _ in ids]