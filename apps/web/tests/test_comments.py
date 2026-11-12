import pytest
from sqlalchemy import delete as sa_delete


@pytest.mark.asyncio
async def test_create_and_list_comment(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    r = await authed_admin_client.post(f"/api/sets/{slug}/comments", json={
        "body": "hello **world**",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert "<strong>world</strong>" in body["body_html"]
    listing = await authed_admin_client.get(f"/api/sets/{slug}/comments")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1


@pytest.mark.asyncio
async def test_list_carries_authors_and_mentions(authed_admin_client, seeded_live_set):
    """The listing loads every author and mentioned user in one go."""
    slug = seeded_live_set["slug"]
    for body in ("first", "ping @admin", "third"):
        r = await authed_admin_client.post(f"/api/sets/{slug}/comments", json={"body": body})
        assert r.status_code == 201, r.text
    items = (await authed_admin_client.get(f"/api/sets/{slug}/comments")).json()["items"]
    assert [i["body_md"] for i in items] == ["first", "ping @admin", "third"]
    assert {i["author"]["username"] for i in items} == {"admin"}
    assert [[m["username"] for m in i["mentions"]] for i in items] == [[], ["admin"], []]


@pytest.mark.asyncio
async def test_reply_one_level(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    top = (await authed_admin_client.post(f"/api/sets/{slug}/comments",
                                           json={"body": "top"})).json()
    r = await authed_admin_client.post(f"/api/sets/{slug}/comments", json={
        "body": "reply", "parent_id": top["id"],
    })
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_reply_to_reply_rejected(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    top = (await authed_admin_client.post(f"/api/sets/{slug}/comments",
                                           json={"body": "top"})).json()
    reply = (await authed_admin_client.post(f"/api/sets/{slug}/comments",
                                             json={"body": "reply", "parent_id": top["id"]})).json()
    r = await authed_admin_client.post(f"/api/sets/{slug}/comments", json={
        "body": "second-level reply", "parent_id": reply["id"],
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_edit_within_window(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    c = (await authed_admin_client.post(f"/api/sets/{slug}/comments",
                                          json={"body": "original"})).json()
    r = await authed_admin_client.patch(f"/api/comments/{c['id']}",
                                          json={"body": "edited"})
    assert r.status_code == 200
    assert "edited" in r.json()["body_md"]


@pytest.mark.asyncio
async def test_soft_delete(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    c = (await authed_admin_client.post(f"/api/sets/{slug}/comments",
                                          json={"body": "delete me"})).json()
    r = await authed_admin_client.delete(f"/api/comments/{c['id']}")
    assert r.status_code == 204
    listing = (await authed_admin_client.get(f"/api/sets/{slug}/comments")).json()
    assert listing["items"][0]["deleted_at"] is not None


@pytest.mark.asyncio
async def test_admin_delete_other_user_writes_audit_event(authed_admin_client, seeded_live_set):
    """Admin deleting another user's comment writes a comment.deleted_by_admin
    audit event. The previous tests all posted+deleted as the admin, which
    skips the auditable branch in delete_comment (is_admin and c.user_id != user.id)."""
    import os
    import uuid as uuidmod
    from datetime import UTC
    from datetime import datetime as dt

    from setvault_core.db import init_engine, session_factory
    from setvault_core.models.engagement_3c import Comment
    from setvault_core.models.identity import User
    from setvault_core.models.system import AuditEvent
    from setvault_core.services.passwords import hash_password
    from sqlalchemy import select

    init_engine(os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://setvault:setvault@localhost:5432/setvault",
    ))

    # Create a non-admin user and a comment owned by them directly via the DB.
    async with session_factory()() as s:
        other = User(
            email="other@example.test", username="other", display_name="Other",
            password_hash=hash_password("hunter2hunter2"), role="user",
        )
        s.add(other)
        await s.flush()
        other_id = other.id
        c = Comment(
            live_set_id=uuidmod.UUID(seeded_live_set["id"]),
            user_id=other_id,
            body="please dont delete",
            mentions_user_ids=[],
            created_at=dt.now(UTC),
        )
        s.add(c)
        await s.flush()
        cid = c.id
        await s.commit()

    # Admin deletes the other user's comment via the API.
    r = await authed_admin_client.delete(f"/api/comments/{cid}")
    assert r.status_code == 204, r.text

    # The auditable branch should have written exactly one row.
    async with session_factory()() as s:
        rows = (await s.execute(
            select(AuditEvent).where(
                AuditEvent.action == "comment.deleted_by_admin",
                AuditEvent.target_id == str(cid),
            )
        )).scalars().all()
        assert len(rows) == 1
        ae = rows[0]
        assert ae.target_type == "comment"
        assert ae.actor_kind == "user"
        assert ae.actor_user_id is not None
        assert ae.before is not None
        assert "please dont delete" in ae.before["body"]
        # Comment row is wiped by _cleanup_engagement_3c; User is not, so
        # clean up the user we created here.
        await s.execute(sa_delete(User).where(User.id == other_id))
        await s.commit()
