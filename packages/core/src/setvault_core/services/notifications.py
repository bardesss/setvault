"""Notification dispatcher — extends the Phase 2B notification-connector
framework with in-app delivery and the new ``mention`` / ``comment_reply``
kinds.

Channel semantics follow Phase 3 spec §5.3.4: when a user has no
``NotificationPreference`` row for ``mention`` or ``comment_reply``, the
default is ``both`` (in-app + email). The model's column-level
``default="email"`` is for explicit ORM inserts that omit the channel; the
upsert endpoint always passes one, so that default never fires for engagement
kinds in practice.

Email enqueueing reaches into the Phase 2B SMTP connector framework via
:func:`setvault_core.services.email_dispatch.enqueue_email`. When no SMTP
connector is configured the email call returns False silently — in-app
delivery still lands and the small-private-group user's bell badge updates.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.config import redis_url
from setvault_core.models.engagement_3c import InAppNotification
from setvault_core.models.identity import NotificationPreference, User
from setvault_core.services.audio_quality import quality_label
from setvault_core.services.email_dispatch import enqueue_email
from setvault_core.services.url_rip import extract_platform_and_id

if TYPE_CHECKING:
    from setvault_core.models.catalog import LiveSet
    from setvault_core.models.engagement_3c import Comment
    from setvault_core.models.upgrades import SetUpgradeEvent

logger = logging.getLogger(__name__)

_EMAIL_SUBJECTS = {
    "mention": "You were mentioned on SetVault",
    "comment_reply": "Someone replied to your comment on SetVault",
    "set_upgraded": "A set in your SetVault library was upgraded",
}


def _base_url() -> str:
    return os.environ.get("BASE_URL", "").rstrip("/")


async def _preference_for(
    session: AsyncSession, user_id: uuid.UUID, kind: str,
) -> NotificationPreference | None:
    """Returns the user's NotificationPreference for this kind, or None.

    A None return indicates "no row" — callers default to channel ``both`` per
    spec §5.3.4.
    """
    return (await session.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.kind == kind,
        )
    )).scalar_one_or_none()


async def _deliver_in_app(
    session: AsyncSession, *, user_id: uuid.UUID, kind: str,
    subject_type: str, subject_id: uuid.UUID, payload: dict,
) -> None:
    n = InAppNotification(
        user_id=user_id, kind=kind, subject_type=subject_type,
        subject_id=subject_id, payload=payload, created_at=datetime.now(UTC),
    )
    session.add(n)
    await session.flush()


async def _deliver_email(
    session: AsyncSession, *, user_id: uuid.UUID, kind: str, payload: dict,
) -> None:
    """Enqueue an email for this notification; no-op if no SMTP connector.

    The job runs through the Phase 2B SMTP connector framework. Failure to
    enqueue (no connector, Redis down) returns False from ``enqueue_email``
    and we swallow it — email is best-effort, in-app delivery is the
    authoritative channel for the bell badge.
    """
    user = await session.get(User, user_id)
    if user is None or not user.email:
        return
    set_slug = payload.get("set_slug", "")
    set_title = payload.get("set_title", "")
    author = payload.get("author_username", "")
    excerpt = payload.get("excerpt", "")
    subject = _EMAIL_SUBJECTS.get(kind, "SetVault notification")
    if kind == "set_upgraded":
        body = (
            f"\"{set_title}\" now has a better copy:\n\n"
            f"  {payload.get('from_label', '')} -> {payload.get('to_label', '')}\n\n"
            f"Open the set: {_base_url()}/sets/{set_slug}\n"
        )
        try:
            await enqueue_email(
                session, redis_url=redis_url(), to=user.email, subject=subject, text=body,
            )
        except Exception:
            logger.exception("notification email enqueue failed")
        return
    body = (
        f"@{author} {('mentioned you' if kind == 'mention' else 'replied to your comment')} "
        f"on \"{set_title}\":\n\n"
        f"  {excerpt}\n\n"
        f"Open the set: {_base_url()}/sets/{set_slug}\n"
    )
    try:
        await enqueue_email(
            session, redis_url=redis_url(), to=user.email, subject=subject, text=body,
        )
    except Exception:
        logger.exception("notification email enqueue failed")


async def dispatch_for_comment(
    session: AsyncSession,
    comment: Comment,
    *, author: User, live_set: LiveSet,
) -> None:
    # Build the recipient set: mentions + parent author (excluding the author themselves)
    recipients: set[uuid.UUID] = set(comment.mentions_user_ids or [])
    kind_for: dict[uuid.UUID, str] = {uid: "mention" for uid in recipients}
    if comment.parent_id:
        from setvault_core.models.engagement_3c import Comment as CommentModel
        parent = await session.get(CommentModel, comment.parent_id)
        if parent and parent.user_id != author.id:
            recipients.add(parent.user_id)
            kind_for.setdefault(parent.user_id, "comment_reply")
    recipients.discard(author.id)
    for uid in recipients:
        kind = kind_for[uid]
        pref = await _preference_for(session, uid, kind)
        # Spec §5.3.4: no row → default to "both" (in-app + email).
        channel = pref.channel if pref else "both"
        payload = {
            "set_slug": live_set.slug,
            "set_title": live_set.title,
            "comment_id": str(comment.id),
            "author_username": author.username,
            "excerpt": comment.body[:200],
        }
        if channel in ("in_app", "both"):
            await _deliver_in_app(
                session, user_id=uid, kind=kind,
                subject_type="comment", subject_id=comment.id, payload=payload,
            )
        if channel in ("email", "both"):
            await _deliver_email(session, user_id=uid, kind=kind, payload=payload)


async def notify_set_upgraded(
    session: AsyncSession, target: LiveSet, event: SetUpgradeEvent,
) -> None:
    """Tell the set's owner a better copy replaced its audio (Phase 7D).

    Channel follows the owner's ``set_upgraded`` preference; no row means
    in-app only (email is opt-in, since a sweep can upgrade many sets). A set
    with no owner has no recipient. The caller commits.
    """
    uid = target.uploaded_by
    if uid is None:
        return
    pref = await _preference_for(session, uid, "set_upgraded")
    channel = pref.channel if pref else "in_app"
    if channel == "off":
        return
    from_label, to_label = event_labels(event)
    payload = {
        "set_slug": target.slug,
        "set_title": target.title,
        "from_label": from_label,
        "to_label": to_label,
    }
    if channel in ("in_app", "both"):
        await _deliver_in_app(
            session, user_id=uid, kind="set_upgraded",
            subject_type="set", subject_id=target.id, payload=payload,
        )
    if channel in ("email", "both"):
        await _deliver_email(session, user_id=uid, kind="set_upgraded", payload=payload)


async def _notify_admins_maintenance(session: AsyncSession, payload: dict) -> int:
    """In-app ``maintenance`` notification to every active admin whose
    ``maintenance`` preference isn't ``off``. Returns the number sent."""
    admins = (await session.execute(
        select(User.id).where(User.role == "admin", User.disabled_at.is_(None))
    )).scalars().all()
    sent = 0
    for uid in admins:
        pref = await _preference_for(session, uid, "maintenance")
        if pref is not None and pref.channel == "off":
            continue
        await _deliver_in_app(
            session, user_id=uid, kind="maintenance",
            subject_type="maintenance", subject_id=uid, payload=payload,
        )
        sent += 1
    return sent


async def notify_backfill_summary(session: AsyncSession, counts: dict) -> int:
    """One in-app ``maintenance`` notification per active admin when the
    quality backfill's duplicate cleanup finishes (Phase 7D spec §4.7: no
    per-merge notifications). An admin whose ``maintenance`` preference is
    ``off`` gets none. Returns the number sent; the caller commits."""
    payload = {k: int(counts.get(k, 0))
               for k in ("fingerprinted", "measured", "merged", "skipped", "errors")}
    return await _notify_admins_maintenance(session, payload)


async def notify_backup_failed(session: AsyncSession, error: str) -> int:
    """One in-app ``maintenance`` notification per active admin when a
    scheduled or manual database backup fails (P2a A5). An admin whose
    ``maintenance`` preference is ``off`` gets none. Returns the number sent;
    the caller commits."""
    payload = {"event": "backup.failed", "error": error}
    return await _notify_admins_maintenance(session, payload)


def event_labels(event: SetUpgradeEvent) -> tuple[str, str]:
    """Readable (from, to) quality labels for an upgrade event."""
    return (
        quality_label(
            event.from_tier, event.from_codec, event.from_bitrate_kbps,
            source_name(event.from_source_type, event.from_source_url)),
        quality_label(
            event.to_tier, event.to_codec, event.to_bitrate_kbps,
            source_name(event.to_source_type, event.to_source_url)),
    )


def source_name(source_type: str | None, source_url: str | None) -> str | None:
    """Resolve ``url_rip`` to its platform (YouTube, Bandcamp...) via the URL.

    Falls back to the raw source type when the URL is missing or unrecognised.
    """
    if source_type == "url_rip" and source_url:
        platform, _ = extract_platform_and_id(source_url)
        if platform != "other":
            return platform
    return source_type
