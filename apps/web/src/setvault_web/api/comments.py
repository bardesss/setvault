from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.models.catalog import LiveSet
from setvault_core.models.engagement_3c import Comment
from setvault_core.models.identity import User
from setvault_core.schemas.comments import (
    CommentAuthor,
    CommentCreateIn,
    CommentEditIn,
    CommentOut,
    CommentsListOut,
)
from setvault_core.services.audit import log as audit_log
from setvault_core.services.comments import (
    CommentValidationError,
    create_comment,
    edit_comment,
    render_markdown_safe,
    soft_delete_comment,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import current_user, db_session, parse_uuid

router = APIRouter(tags=["comments"])


def _author_for(user: User) -> CommentAuthor:
    return CommentAuthor(id=str(user.id), username=user.username,
                         display_name=user.display_name)


async def _out(session: AsyncSession, c: Comment) -> CommentOut:
    # TODO(perf): N+1 — list_comments calls _out per row, so each comment
    # triggers an author session.get + up to one mention IN-query. Fine for
    # the small-private-group target (<10 users, threads in the tens). When
    # threads grow into the hundreds, hydrate authors + mentions in two bulk
    # queries upstream and pass them in.
    author = await session.get(User, c.user_id)
    mentions: list[CommentAuthor] = []
    if c.mentions_user_ids:
        mention_rows = (await session.execute(
            select(User).where(User.id.in_(c.mentions_user_ids))
        )).scalars().all()
        mentions = [_author_for(u) for u in mention_rows]
    return CommentOut(
        id=str(c.id),
        parent_id=str(c.parent_id) if c.parent_id else None,
        position_seconds=c.position_seconds,
        body_html=("" if c.deleted_at else render_markdown_safe(c.body)),
        body_md=("" if c.deleted_at else c.body),
        author=_author_for(author),
        mentions=mentions,
        edited_at=c.edited_at,
        deleted_at=c.deleted_at,
        created_at=c.created_at,
    )


@router.get("/api/sets/{slug}/comments", response_model=CommentsListOut)
async def list_comments(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[User, Depends(current_user)],
    limit: int = 50, offset: int = 0,
):
    live = (await session.execute(
        select(LiveSet).where(LiveSet.slug == slug, LiveSet.deleted_at.is_(None))
    )).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404)
    rows = (await session.execute(
        select(Comment).where(Comment.live_set_id == live.id)
        .order_by(Comment.created_at).limit(limit).offset(offset)
    )).scalars().all()
    total = (await session.execute(
        select(func.count()).select_from(Comment).where(Comment.live_set_id == live.id)
    )).scalar_one()
    items: list[CommentOut] = []
    for c in rows:
        items.append(await _out(session, c))
    return CommentsListOut(items=items, total=total)


@router.post("/api/sets/{slug}/comments", response_model=CommentOut, status_code=201)
async def post_comment(
    slug: str,
    body: CommentCreateIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = (await session.execute(
        select(LiveSet).where(LiveSet.slug == slug, LiveSet.deleted_at.is_(None))
    )).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404)
    try:
        c = await create_comment(
            session, live_set_id=live.id, user_id=user.id,
            body=body.body,
            parent_id=(
                parse_uuid(body.parent_id, status_code=422, detail="invalid id")
                if body.parent_id else None
            ),
            position_seconds=body.position_seconds,
        )
    except CommentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Dispatch notifications (mentions + reply)
    from setvault_core.services.notifications import dispatch_for_comment
    await dispatch_for_comment(session, c, author=user, live_set=live)
    await session.commit()
    return await _out(session, c)


@router.patch("/api/comments/{comment_id}", response_model=CommentOut)
async def patch_comment(
    comment_id: str,
    body: CommentEditIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    c = await session.get(Comment, parse_uuid(comment_id))
    if c is None:
        raise HTTPException(status_code=404)
    is_admin = (user.role == "admin")
    try:
        await edit_comment(session, c, user_id=user.id, body=body.body, is_admin=is_admin)
    except CommentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return await _out(session, c)


@router.delete("/api/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: str,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    c = await session.get(Comment, parse_uuid(comment_id))
    if c is None:
        raise HTTPException(status_code=404)
    is_admin = (user.role == "admin")
    try:
        await soft_delete_comment(session, c, user_id=user.id, is_admin=is_admin)
    except CommentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if is_admin and c.user_id != user.id:
        await audit_log(
            session, actor_user_id=user.id, actor_kind="user",
            action="comment.deleted_by_admin",
            target_type="comment", target_id=str(c.id),
            before={"body": c.body[:200]},
        )
    await session.commit()
