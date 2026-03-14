from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound

from saleacc_bot.config import Settings, get_settings
from saleacc_bot.models import Order

ORDER_HEADERS = [
    "order_id",
    "created_at",
    "updated_at",
    "status",
    "product_slug",
    "product_title",
    "quantity",
    "customer_email",
    "buyer_tg_id",
    "buyer_username",
    "unit_price",
    "total_price",
    "currency",
    "payment_method",
    "payment_id",
    "payment_status",
    "confirmation_url",
    "assigned_stock_item_id",
    "paid_at",
    "reserved_until",
    "cancelled_at",
    "delivered_at",
    "cancellation_reason",
]

_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SheetOrderRow:
    values: dict[str, str]


class GoogleSheetsUnavailableError(RuntimeError):
    pass


class SheetsStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = asyncio.Lock()
        self._gc: gspread.Client | None = None
        self._service_account_email: str | None = None
        self._disabled_reason: str | None = None

    async def ensure_schema(self) -> bool:
        async with self._lock:
            if self._disabled_reason:
                return False
            try:
                await asyncio.to_thread(self._ensure_schema_sync)
            except GoogleSheetsUnavailableError as exc:
                self._disable(str(exc))
                return False
            return True

    async def upsert_order(self, order: Order) -> None:
        async with self._lock:
            if self._disabled_reason:
                return
            try:
                await asyncio.to_thread(self._upsert_order_sync, self._serialize_order(order))
            except GoogleSheetsUnavailableError as exc:
                self._disable(str(exc))

    async def list_recent_orders(self, limit: int = 20) -> list[dict[str, str]]:
        async with self._lock:
            if self._disabled_reason:
                return []
            try:
                return await asyncio.to_thread(self._list_recent_orders_sync, limit)
            except GoogleSheetsUnavailableError as exc:
                self._disable(str(exc))
                return []

    def _ensure_schema_sync(self) -> None:
        ws = self._orders_ws()
        values = ws.get_all_values()
        if not values:
            ws.append_row(ORDER_HEADERS, value_input_option="USER_ENTERED")
            return
        current_headers = values[0]
        if current_headers == ORDER_HEADERS:
            return

        if len(values) == 1:
            ws.update("A1", [ORDER_HEADERS], value_input_option="USER_ENTERED")
            return

        extra_rows = values[1:]
        ws.clear()
        ws.append_row(ORDER_HEADERS, value_input_option="USER_ENTERED")
        if extra_rows:
            normalized_rows: list[list[str]] = []
            current_map = {header: idx for idx, header in enumerate(current_headers)}
            for row in extra_rows:
                normalized_rows.append([row[current_map[header]] if header in current_map and current_map[header] < len(row) else "" for header in ORDER_HEADERS])
            ws.append_rows(normalized_rows, value_input_option="USER_ENTERED")

    def _upsert_order_sync(self, row: SheetOrderRow) -> None:
        ws = self._orders_ws()
        values = ws.get_all_values()
        if not values:
            ws.append_row(ORDER_HEADERS, value_input_option="USER_ENTERED")
            values = [ORDER_HEADERS]

        order_id_index = 0
        row_values = [row.values.get(header, "") for header in ORDER_HEADERS]
        for row_number, existing in enumerate(values[1:], start=2):
            if order_id_index < len(existing) and existing[order_id_index] == row.values["order_id"]:
                end_col = _col_to_a1(len(ORDER_HEADERS))
                ws.update(f"A{row_number}:{end_col}{row_number}", [row_values], value_input_option="USER_ENTERED")
                return

        ws.append_row(row_values, value_input_option="USER_ENTERED")

    def _list_recent_orders_sync(self, limit: int) -> list[dict[str, str]]:
        ws = self._orders_ws()
        values = ws.get_all_values()
        if len(values) <= 1:
            return []
        headers = values[0]
        rows = [dict(zip(headers, row + [""] * (len(headers) - len(row)))) for row in values[1:]]
        rows.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return rows[:limit]

    def _orders_ws(self):
        if self._disabled_reason:
            raise GoogleSheetsUnavailableError(self._disabled_reason)
        try:
            spreadsheet = self._client().open_by_key(self._settings.google_sheet_id)
        except (APIError, PermissionError, SpreadsheetNotFound) as exc:
            raise GoogleSheetsUnavailableError(_format_google_access_error(exc, self._settings, self._service_account_email)) from exc
        try:
            return spreadsheet.worksheet(self._settings.google_orders_worksheet)
        except WorksheetNotFound:
            return spreadsheet.add_worksheet(self._settings.google_orders_worksheet, rows=2000, cols=30)

    def _client(self) -> gspread.Client:
        if self._gc is None:
            credentials = _build_google_credentials(self._settings)
            self._service_account_email = getattr(credentials, "service_account_email", None)
            self._gc = gspread.authorize(credentials)
        return self._gc

    def _disable(self, reason: str) -> None:
        if self._disabled_reason == reason:
            return
        self._disabled_reason = reason
        logger.warning("Google Sheets integration disabled: %s", reason)

    def _serialize_order(self, order: Order) -> SheetOrderRow:
        def _dt(value: datetime | None) -> str:
            if value is None:
                return ""
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat()

        values = {
            "order_id": order.id,
            "created_at": _dt(order.created_at),
            "updated_at": _dt(order.updated_at),
            "status": order.status,
            "product_slug": order.product_slug,
            "product_title": order.product_title,
            "quantity": str(order.quantity),
            "customer_email": order.customer_email,
            "buyer_tg_id": str(order.tg_user_id),
            "buyer_username": order.tg_username or "",
            "unit_price": str(order.unit_price),
            "total_price": str(order.total_price),
            "currency": order.currency,
            "payment_method": order.payment_method,
            "payment_id": order.provider_payment_id or "",
            "payment_status": order.provider_status or "",
            "confirmation_url": order.payment_confirmation_url or "",
            "assigned_stock_item_id": order.assigned_stock_item_id or "",
            "paid_at": _dt(order.paid_at),
            "reserved_until": _dt(order.reserved_until),
            "cancelled_at": _dt(order.cancelled_at),
            "delivered_at": _dt(order.delivered_at),
            "cancellation_reason": order.cancellation_reason or "",
        }
        return SheetOrderRow(values=values)


@lru_cache(maxsize=1)
def get_sheets_store() -> SheetsStore:
    return SheetsStore(get_settings())


def _build_google_credentials(settings: Settings) -> Credentials:
    if settings.google_service_account_json_b64:
        try:
            normalized = "".join(settings.google_service_account_json_b64.split())
            decoded = base64.b64decode(normalized, validate=True).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON_B64 is not valid base64") from exc
        try:
            info = json.loads(decoded)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON_B64 does not contain valid JSON") from exc
        if not isinstance(info, dict):
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON_B64 must decode to a Google service account JSON object")
        return Credentials.from_service_account_info(info, scopes=_SCOPES)
    if settings.google_service_account_json:
        try:
            info = json.loads(settings.google_service_account_json)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON") from exc
        if not isinstance(info, dict):
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON must be a Google service account JSON object")
        return Credentials.from_service_account_info(info, scopes=_SCOPES)
    if settings.google_service_account_file:
        return Credentials.from_service_account_file(settings.google_service_account_file, scopes=_SCOPES)
    raise RuntimeError(
        "Google service account is not configured. Set GOOGLE_SERVICE_ACCOUNT_FILE, "
        "GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_JSON_B64."
    )


def _format_google_access_error(
    exc: Exception,
    settings: Settings,
    service_account_email: str | None,
) -> str:
    message = str(exc)
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        message = f"{message} {cause}"
    normalized = message.lower()

    spreadsheet_hint = f"spreadsheet {settings.google_sheet_id}"
    share_hint = ""
    if service_account_email:
        share_hint = f" and share {spreadsheet_hint} with {service_account_email}"

    if "has not been used in project" in normalized or "it is disabled" in normalized:
        return (
            "Google Sheets API is disabled for the Google Cloud project of the service account. "
            "Enable `Google Sheets API` in Google Cloud Console, wait a few minutes, then restart the service."
        )
    if isinstance(exc, SpreadsheetNotFound) or "spreadsheet not found" in normalized:
        return (
            f"Google spreadsheet {settings.google_sheet_id} was not found or is not accessible. "
            f"Verify GOOGLE_SHEET_ID{share_hint}."
        )
    if isinstance(exc, PermissionError) or "permission" in normalized or "forbidden" in normalized or "403" in normalized:
        return (
            f"Google service account does not have access to {spreadsheet_hint}. "
            f"Verify GOOGLE_SHEET_ID, enable Google Sheets API{share_hint}, then restart the service."
        )
    return f"Google Sheets request failed: {message}"


def _col_to_a1(index: int) -> str:
    if index < 1:
        raise ValueError("index must be >= 1")
    letters = []
    current = index
    while current:
        current, remainder = divmod(current - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))
