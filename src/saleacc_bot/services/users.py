from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from saleacc_bot.models import BotUser, Order


async def touch_user(
    session: AsyncSession,
    *,
    tg_user_id: int,
    tg_username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> None:
    now = datetime.now(timezone.utc)
    user = await session.get(BotUser, tg_user_id)
    if user is None:
        session.add(
            BotUser(
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                first_name=first_name,
                last_name=last_name,
                is_blocked=False,
                last_seen_at=now,
            )
        )
    else:
        user.tg_username = tg_username
        user.first_name = first_name
        user.last_name = last_name
        user.is_blocked = False
        user.last_seen_at = now

    await session.commit()


async def list_broadcast_user_ids(session: AsyncSession) -> list[int]:
    direct = list(await session.scalars(select(BotUser.tg_user_id).where(BotUser.is_blocked.is_(False))))
    blocked = set(await session.scalars(select(BotUser.tg_user_id).where(BotUser.is_blocked.is_(True))))
    from_orders = list(await session.scalars(select(Order.tg_user_id).distinct()))

    merged = {int(x) for x in direct}
    merged.update(int(x) for x in from_orders if int(x) not in blocked)
    return sorted(merged)


async def mark_users_blocked(session: AsyncSession, tg_user_ids: list[int]) -> None:
    if not tg_user_ids:
        return
    existing_ids = set(await session.scalars(select(BotUser.tg_user_id).where(BotUser.tg_user_id.in_(tg_user_ids))))
    missing_ids = [uid for uid in tg_user_ids if uid not in existing_ids]
    for uid in missing_ids:
        session.add(BotUser(tg_user_id=uid, is_blocked=True))
    await session.execute(
        update(BotUser).where(BotUser.tg_user_id.in_(tg_user_ids)).values(is_blocked=True)
    )
    await session.commit()


async def get_audience_stats(session: AsyncSession) -> dict[str, int]:
    total_users = len(list(await session.scalars(select(BotUser.tg_user_id))))
    blocked_users = len(
        list(await session.scalars(select(BotUser.tg_user_id).where(BotUser.is_blocked.is_(True))))
    )
    known_recipients = len(await list_broadcast_user_ids(session))
    return {
        "known_users": total_users,
        "blocked_users": blocked_users,
        "broadcast_recipients": known_recipients,
    }
