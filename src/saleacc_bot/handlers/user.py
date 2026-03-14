from __future__ import annotations

import re

from aiogram import F, Router
from contextlib import suppress

from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from saleacc_bot.config import get_settings
from saleacc_bot.db import get_session
from saleacc_bot.keyboards import (
    email_choice_keyboard,
    orders_keyboard,
    pay_order_keyboard,
    product_keyboard,
    section_keyboard,
    support_keyboard,
    user_reply_keyboard,
)
from saleacc_bot.services.catalog import get_product_by_slug, get_product_category, list_active_products
from saleacc_bot.services.notifications import notify_order_paid
from saleacc_bot.services.orders import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_PAID,
    attach_provider_payment,
    create_order,
    get_order,
    list_user_orders,
    mark_order_cancelled,
    mark_order_failed,
    mark_order_paid,
)
from saleacc_bot.services.sheets_store import get_sheets_store
from saleacc_bot.services.stock import claim_chatgpt_account, order_needs_auto_delivery, release_chatgpt_reservation, reserve_chatgpt_account
from saleacc_bot.services.users import get_user, set_user_email, touch_user
from saleacc_bot.services.yookassa import YooKassaClient
from saleacc_bot.states import CheckoutStates
from saleacc_bot.ui import (
    main_menu_text,
    main_menu_image_path,
    orders_text,
    payment_caption,
    product_text,
    section_image_path,
    section_text,
    store_menu_payload,
)

router = Router(name="user")
settings = get_settings()
yookassa_client = YooKassaClient(settings)
EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
HELP_TEXT = (
    "💬 <b>Поддержка</b>\n"
    "Если есть вопрос или проблема — пиши:\n\n"
    "Отвечаем с 9:00 до 23:00 МСК"
)


async def _send_content(*, bot, chat_id: int, text: str, reply_markup=None, photo_path=None) -> None:
    if photo_path is not None and photo_path.is_file():
        await bot.send_photo(
            chat_id=chat_id,
            photo=FSInputFile(str(photo_path)),
            caption=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        return
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode="HTML")


async def _delete_callback_message(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass


async def _replace_message(callback: CallbackQuery, text: str, reply_markup=None, *, photo_path=None) -> None:
    chat_id = callback.message.chat.id if callback.message is not None else callback.from_user.id
    await _delete_callback_message(callback)
    await _send_content(
        bot=callback.bot,
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        photo_path=photo_path,
    )


async def _render_main(callback: CallbackQuery) -> None:
    await _replace_message(
        callback,
        main_menu_text(),
        user_reply_keyboard(),
        photo_path=main_menu_image_path(),
    )


async def _show_main_menu_for_message(message: Message, state: FSMContext | None = None) -> None:
    if state is not None:
        await state.clear()
    await _send_content(
        bot=message.bot,
        chat_id=message.chat.id,
        text=main_menu_text(),
        reply_markup=user_reply_keyboard(),
        photo_path=main_menu_image_path(),
    )


async def _show_store_menu_for_message(message: Message, state: FSMContext | None = None) -> None:
    if state is not None:
        await state.clear()
    text, keyboard = store_menu_payload()
    await _send_content(
        bot=message.bot,
        chat_id=message.chat.id,
        text=text,
        reply_markup=keyboard,
        photo_path=main_menu_image_path(),
    )


async def _render_store_menu(callback: CallbackQuery) -> None:
    text, keyboard = store_menu_payload()
    await _replace_message(callback, text, keyboard, photo_path=main_menu_image_path())


async def _start_checkout(*, chat_id: int, user_id: int, username: str | None, product_slug: str, email: str, bot) -> tuple[bool, str]:
    async with get_session() as session:
        product = await get_product_by_slug(session, product_slug)
        if product is None:
            return False, "Тариф недоступен."

        order = await create_order(
            session,
            user_id=user_id,
            username=username,
            customer_email=email,
            product=product,
        )
        try:
            payment = await yookassa_client.create_payment(order=order)
            order = await attach_provider_payment(
                session,
                order_id=order.id,
                payment_id=payment.payment_id,
                confirmation_url=payment.confirmation_url or "",
                provider_status=payment.status,
            )
        except Exception as exc:  # noqa: BLE001
            await mark_order_failed(
                session,
                order_id=order.id,
                provider_status="creation_failed",
                reason=str(exc)[:250],
            )
            order = await get_order(session, order.id)
            if order is not None:
                await get_sheets_store().upsert_order(order)
            return False, "Не удалось создать платеж в ЮKassa. Проверь настройки магазина и webhook."

        if order is None or not payment.confirmation_url:
            if order is not None:
                await mark_order_failed(
                    session,
                    order_id=order.id,
                    provider_status=payment.status or "invalid_response",
                    reason="YooKassa response does not contain confirmation_url",
                )
                failed_order = await get_order(session, order.id)
                if failed_order is not None:
                    await get_sheets_store().upsert_order(failed_order)
            return False, "ЮKassa вернула неполный ответ. Проверь настройки магазина."

        if order_needs_auto_delivery(order):
            try:
                reserved_account = await reserve_chatgpt_account(session, settings, order)
            except RuntimeError as exc:
                try:
                    await yookassa_client.cancel_payment(payment.payment_id)
                except Exception:
                    pass
                await mark_order_failed(
                    session,
                    order_id=order.id,
                    provider_status=payment.status or "stock_config_error",
                    reason=str(exc)[:250],
                )
                failed_order = await get_order(session, order.id)
                if failed_order is not None:
                    await get_sheets_store().upsert_order(failed_order)
                return False, f"Автовыдача GPT сейчас недоступна. {exc}"
            if reserved_account is None:
                try:
                    await yookassa_client.cancel_payment(payment.payment_id)
                except Exception:
                    pass
                await mark_order_failed(
                    session,
                    order_id=order.id,
                    provider_status=payment.status or "stock_unavailable",
                    reason="No ChatGPT stock available for reservation",
                )
                failed_order = await get_order(session, order.id)
                if failed_order is not None:
                    await get_sheets_store().upsert_order(failed_order)
                return False, "Сейчас нет свободных GPT-аккаунтов для резерва. Попробуйте позже."

        await get_sheets_store().upsert_order(order)
        await bot.send_message(
            chat_id=chat_id,
            text=payment_caption(product=product, email=email, order_id=order.id, offer_url=settings.public_offer_url),
            reply_markup=pay_order_keyboard(confirmation_url=payment.confirmation_url, order_id=order.id),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True, order.id


async def _sync_order_from_provider(*, order_id: str, bot) -> tuple[bool, str]:
    async with get_session() as session:
        order = await get_order(session, order_id)
        if order is None:
            return False, "Заказ не найден."
        if not order.provider_payment_id:
            return False, "У заказа нет ID платежа."

        payment = await yookassa_client.get_payment(order.provider_payment_id)
        if payment.metadata.get("order_id") and payment.metadata["order_id"] != order.id:
            return False, "ЮKassa вернула платеж от другого заказа."

        if payment.status == "succeeded":
            was_paid = order.status == ORDER_STATUS_PAID
            order = await mark_order_paid(
                session,
                order_id=order.id,
                provider_payment_id=payment.payment_id,
                provider_status=payment.status,
            )
            if order is None:
                return False, "Не удалось обновить заказ."
            delivered_account = None
            if order_needs_auto_delivery(order):
                try:
                    delivered_account = await claim_chatgpt_account(session, settings, order)
                except RuntimeError:
                    delivered_account = None
            await get_sheets_store().upsert_order(order)
            if not was_paid:
                await notify_order_paid(bot, settings, order, stock_account=delivered_account)
            return True, "Оплата подтверждена."

        if payment.status == "canceled":
            order = await mark_order_cancelled(
                session,
                order_id=order.id,
                provider_status=payment.status,
                reason="YooKassa canceled payment",
            )
            if order is not None:
                if order_needs_auto_delivery(order):
                    await release_chatgpt_reservation(session, order)
                await get_sheets_store().upsert_order(order)
            return False, "Платеж отменен в ЮKassa."

        order.provider_status = payment.status
        if payment.confirmation_url:
            order.payment_confirmation_url = payment.confirmation_url
        await session.commit()
        await get_sheets_store().upsert_order(order)
        return False, f"Платеж пока в статусе: {payment.status}"


@router.message(CommandStart())
async def on_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with get_session() as session:
        await touch_user(
            session,
            tg_user_id=message.from_user.id,
            tg_username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
    await _show_main_menu_for_message(message)


@router.message(F.text == "🛍 Магазин")
async def on_store_message(message: Message, state: FSMContext) -> None:
    await _show_store_menu_for_message(message, state)


@router.message(F.text == "📲Помощь")
async def on_help_message(message: Message) -> None:
    keyboard = support_keyboard(settings.support_url)
    if keyboard is None:
        await message.answer(
            HELP_TEXT + "\n\nПоддержка временно недоступна. Администратору нужно исправить SUPPORT_URL.",
            parse_mode="HTML",
        )
        return
    await message.answer(HELP_TEXT, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "main")
async def on_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _render_main(callback)
    await callback.answer()


@router.callback_query(F.data == "main_new")
async def on_main_new(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    chat_id = callback.message.chat.id if callback.message is not None else callback.from_user.id
    await _send_content(
        bot=callback.bot,
        chat_id=chat_id,
        text=main_menu_text(),
        reply_markup=user_reply_keyboard(),
        photo_path=main_menu_image_path(),
    )
    await callback.answer()


@router.callback_query(F.data == "catalog")
async def on_catalog(callback: CallbackQuery) -> None:
    await _render_store_menu(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("section:"))
async def on_section(callback: CallbackQuery) -> None:
    category = callback.data.split(":", maxsplit=1)[1]
    if category not in {"chatgpt", "gemini"}:
        await callback.answer("Раздел недоступен.", show_alert=True)
        return
    async with get_session() as session:
        products = [product for product in await list_active_products(session) if get_product_category(product.slug) == category]
    if not products:
        await callback.answer("Раздел временно недоступен.", show_alert=True)
        return
    await _replace_message(
        callback,
        section_text(category),
        section_keyboard(products),
        photo_path=section_image_path(category),
    )
    await callback.answer()


@router.callback_query(F.data == "orders")
async def on_orders(callback: CallbackQuery) -> None:
    async with get_session() as session:
        orders = list(await list_user_orders(session, user_id=callback.from_user.id, limit=10))
    await _replace_message(callback, orders_text(orders), orders_keyboard())
    await callback.answer()


@router.callback_query(F.data == "support_unavailable")
async def on_support_unavailable(callback: CallbackQuery) -> None:
    await callback.answer("Поддержка временно недоступна. Администратору нужно исправить SUPPORT_URL.", show_alert=True)


@router.callback_query(F.data.startswith("product:"))
async def on_product(callback: CallbackQuery) -> None:
    product_slug = callback.data.split(":", maxsplit=1)[1]
    async with get_session() as session:
        product = await get_product_by_slug(session, product_slug)
    if product is None:
        await callback.answer("Тариф недоступен.", show_alert=True)
        return
    category = get_product_category(product.slug) or "chatgpt"
    back_callback = f"section:{category}"
    await _replace_message(callback, product_text(product), product_keyboard(product.slug, back_callback=back_callback))
    await callback.answer()


@router.callback_query(F.data.startswith("buy:"))
async def on_buy(callback: CallbackQuery, state: FSMContext) -> None:
    product_slug = callback.data.split(":", maxsplit=1)[1]
    async with get_session() as session:
        user = await get_user(session, callback.from_user.id)
        product = await get_product_by_slug(session, product_slug)
    if product is None:
        await callback.answer("Тариф недоступен.", show_alert=True)
        return

    await state.update_data(product_slug=product_slug)
    if user and user.email:
        await _replace_message(
            callback,
            (
                f"<b>{product.title}</b>\n\n"
                f"<b>Сохраненный e-mail для чека:</b> <code>{user.email}</code>\n\n"
                "Можно использовать этот адрес или указать другой."
            ),
            email_choice_keyboard(product_slug=product_slug, email=user.email),
        )
    else:
        await state.set_state(CheckoutStates.waiting_for_email)
        await _replace_message(
            callback,
            (
                f"<b>{product.title}</b>\n\n"
                "Отправьте e-mail, который нужно передать в ЮKassa для электронного чека."
            ),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("email_use:"))
async def on_email_use(callback: CallbackQuery, state: FSMContext) -> None:
    product_slug = callback.data.split(":", maxsplit=1)[1]
    async with get_session() as session:
        user = await get_user(session, callback.from_user.id)
    if user is None or not user.email:
        await state.update_data(product_slug=product_slug)
        await state.set_state(CheckoutStates.waiting_for_email)
        await _replace_message(callback, "Отправьте e-mail для электронного чека.")
        await callback.answer()
        return

    await state.clear()
    ok, result = await _start_checkout(
        chat_id=callback.message.chat.id if callback.message else callback.from_user.id,
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        product_slug=product_slug,
        email=user.email,
        bot=callback.bot,
    )
    await _delete_callback_message(callback)
    await callback.answer("Заказ создан" if ok else result, show_alert=not ok)


@router.callback_query(F.data.startswith("email_change:"))
async def on_email_change(callback: CallbackQuery, state: FSMContext) -> None:
    product_slug = callback.data.split(":", maxsplit=1)[1]
    await state.update_data(product_slug=product_slug)
    await state.set_state(CheckoutStates.waiting_for_email)
    await _replace_message(callback, "Отправьте новый e-mail для электронного чека.")
    await callback.answer()


@router.message(CheckoutStates.waiting_for_email)
async def on_email_message(message: Message, state: FSMContext) -> None:
    email = (message.text or "").strip()
    if not EMAIL_RE.match(email):
        await message.answer("Некорректный e-mail. Отправьте адрес в формате <code>name@example.com</code>", parse_mode="HTML")
        return

    data = await state.get_data()
    product_slug = str(data.get("product_slug") or "").strip()
    if not product_slug:
        await state.clear()
        await message.answer("Не удалось определить выбранный тариф. Начните заново через /start")
        return

    async with get_session() as session:
        await touch_user(
            session,
            tg_user_id=message.from_user.id,
            tg_username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        await set_user_email(session, tg_user_id=message.from_user.id, email=email)

    await state.clear()
    ok, result = await _start_checkout(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        username=message.from_user.username,
        product_slug=product_slug,
        email=email,
        bot=message.bot,
    )
    if not ok:
        await message.answer(result)


@router.callback_query(F.data.startswith("order_cancel:"))
async def on_order_cancel(callback: CallbackQuery) -> None:
    order_id = callback.data.split(":", maxsplit=1)[1]
    async with get_session() as session:
        order = await get_order(session, order_id)
        if order is None or order.tg_user_id != callback.from_user.id:
            await callback.answer("Заказ не найден.", show_alert=True)
            return
        if order.status == ORDER_STATUS_PAID:
            await callback.answer("Заказ уже оплачен.", show_alert=True)
            return

        provider_status = order.provider_status or ORDER_STATUS_CANCELLED
        if order.provider_payment_id:
            try:
                payment = await yookassa_client.cancel_payment(order.provider_payment_id)
                provider_status = payment.status or provider_status
            except Exception:
                pass

        order = await mark_order_cancelled(
            session,
            order_id=order.id,
            provider_status=provider_status,
            reason="Cancelled by user",
        )
        if order is not None:
            if order_needs_auto_delivery(order):
                await release_chatgpt_reservation(session, order)
            await get_sheets_store().upsert_order(order)

    await _render_main(callback)
    await callback.answer("Заказ отменен.")
