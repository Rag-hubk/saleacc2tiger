from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from saleacc_bot.models import BotUser


async def touch_user(
    session: AsyncSession,
    *,
    tg_user_id: int,
    tg_username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> BotUser:
    user = await session.get(BotUser, tg_user_id)
    if user is None:
        user = BotUser(
            tg_user_id=tg_user_id,
            tg_username=tg_username,
            first_name=first_name,
            last_name=last_name,
            is_blocked=False,
        )
        session.add(user)
    else:
        user.tg_username = tg_username
        user.first_name = first_name
        user.last_name = last_name
        user.is_blocked = False

    now = datetime.now(timezone.utc)
    user.last_seen_at = now
    user.updated_at = now
    await session.commit()
    await session.refresh(user)
    return user


async def set_user_email(session: AsyncSession, *, tg_user_id: int, email: str) -> BotUser | None:
    user = await session.get(BotUser, tg_user_id)
    if user is None:
        return None
    user.email = email
    await session.commit()
    await session.refresh(user)
    return user


async def get_user(session: AsyncSession, tg_user_id: int) -> BotUser | None:
    return await session.get(BotUser, tg_user_id)


async def list_known_user_ids(session: AsyncSession) -> list[int]:
    result = await session.scalars(select(BotUser.tg_user_id).where(BotUser.is_blocked.is_(False)))
    return [int(item) for item in result]


async def mark_users_blocked(session: AsyncSession, tg_user_ids: list[int]) -> None:
    if not tg_user_ids:
        return
    await session.execute(
        update(BotUser)
        .where(BotUser.tg_user_id.in_(tg_user_ids))
        .values(is_blocked=True)
    )
    await session.commit()


async def get_audience_stats(session: AsyncSession) -> dict[str, int]:
    total_users = int(await session.scalar(select(func.count()).select_from(BotUser)) or 0)
    blocked_users = int(
        await session.scalar(select(func.count()).select_from(BotUser).where(BotUser.is_blocked.is_(True))) or 0
    )
    return {
        "known_users": total_users,
        "blocked_users": blocked_users,
        "broadcast_recipients": max(0, total_users - blocked_users),
    }
