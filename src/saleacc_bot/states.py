from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class CheckoutStates(StatesGroup):
    waiting_for_email = State()


class AdminDeliveryStates(StatesGroup):
    waiting_for_delivery_text = State()


class AdminBroadcastStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_buttons = State()
