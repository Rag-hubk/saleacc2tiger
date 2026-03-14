from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
from sqlalchemy import select

from saleacc_bot.config import Settings, get_settings
from saleacc_bot.db import get_session
from saleacc_bot.models import Order
from saleacc_bot.services.catalog import get_product_category, get_product_spec

SALES_HEADERS = [
    "sale_id",
    "paid_at",
    "delivered_at",
    "buyer_tg_id",
    "buyer_username",
    "customer_email",
    "product_key",
    "product_title",
    "amount",
    "currency",
    "payment_id",
    "payment_status",
    "inventory_key",
]

INVENTORY_HEADERS = [
    "inventory_key",
    "product_key",
    "product_title",
    "delivery_mode",
    "source",
    "status",
    "order_id",
    "reserved_until",
    "sold_at",
    "access_login",
    "access_secret",
    "note",
    "updated_at",
]

_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SheetRow:
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
                await asyncio.to_thread(self._seed_inventory_sync)
                await self._sync_sales_locked()
            except GoogleSheetsUnavailableError as exc:
                self._disable(str(exc))
                return False
            return True

    async def upsert_order(self, order: Order) -> None:
        async with self._lock:
            if self._disabled_reason:
                return
            try:
                await self._sync_sales_locked()
            except GoogleSheetsUnavailableError as exc:
                self._disable(str(exc))

    async def cleanup_expired_inventory_reservations(self) -> list[str]:
        async with self._lock:
            if self._disabled_reason:
                return []
            try:
                return await asyncio.to_thread(self._cleanup_expired_inventory_reservations_sync)
            except GoogleSheetsUnavailableError as exc:
                self._disable(str(exc))
                return []

    async def reserve_inventory_item(
        self,
        *,
        order_id: str,
        product_key: str,
        product_title: str,
        reserve_minutes: int,
    ) -> dict[str, str] | None:
        async with self._lock:
            if self._disabled_reason:
                raise RuntimeError(self._disabled_reason)
            try:
                return await asyncio.to_thread(
                    self._reserve_inventory_item_sync,
                    order_id,
                    product_key,
                    product_title,
                    reserve_minutes,
                )
            except GoogleSheetsUnavailableError as exc:
                self._disable(str(exc))
                return None

    async def claim_inventory_item(
        self,
        *,
        order_id: str,
        product_key: str,
        product_title: str,
        reserve_minutes: int,
    ) -> dict[str, str] | None:
        async with self._lock:
            if self._disabled_reason:
                raise RuntimeError(self._disabled_reason)
            try:
                return await asyncio.to_thread(
                    self._claim_inventory_item_sync,
                    order_id,
                    product_key,
                    product_title,
                    reserve_minutes,
                )
            except GoogleSheetsUnavailableError as exc:
                self._disable(str(exc))
                return None

    async def release_inventory_reservation(self, *, order_id: str) -> None:
        async with self._lock:
            if self._disabled_reason:
                return
            try:
                await asyncio.to_thread(self._release_inventory_reservation_sync, order_id)
            except GoogleSheetsUnavailableError as exc:
                self._disable(str(exc))

    async def list_recent_orders(self, limit: int = 20) -> list[dict[str, str]]:
        async with self._lock:
            if self._disabled_reason:
                return []
            try:
                return await asyncio.to_thread(self._list_recent_sales_sync, limit)
            except GoogleSheetsUnavailableError as exc:
                self._disable(str(exc))
                return []

    async def _sync_sales_locked(self) -> None:
        rows = await self._build_sales_rows()
        await asyncio.to_thread(self._replace_worksheet_rows_sync, self._settings.google_sales_worksheet, SALES_HEADERS, rows)

    def _ensure_schema_sync(self) -> None:
        self._ensure_worksheet_headers_sync(self._sales_ws(), SALES_HEADERS)
        self._ensure_worksheet_headers_sync(self._inventory_ws(), INVENTORY_HEADERS)

    async def _build_sales_rows(self) -> list[SheetRow]:
        async with get_session() as session:
            result = await session.scalars(
                select(Order)
                .where(Order.status == "paid")
                .order_by(Order.paid_at.desc().nullslast(), Order.created_at.desc())
            )
            orders = list(result)
        return [self._serialize_sale(order) for order in orders]

    def _replace_worksheet_rows_sync(self, worksheet_name: str, headers: list[str], rows: list[SheetRow]) -> None:
        ws = self._worksheet(worksheet_name)
        data = [headers]
        data.extend([[row.values.get(header, "") for header in headers] for row in rows])
        ws.clear()
        ws.update("A1", data, value_input_option="USER_ENTERED")

    def _list_recent_sales_sync(self, limit: int) -> list[dict[str, str]]:
        ws = self._sales_ws()
        values = ws.get_all_values()
        if len(values) <= 1:
            return []
        rows = _normalized_rows(values, SALES_HEADERS)[1:]
        rows.sort(key=lambda item: item.get("paid_at", ""), reverse=True)
        return rows[:limit]

    def _sales_ws(self):
        return self._worksheet(self._settings.google_sales_worksheet)

    def _inventory_ws(self):
        return self._worksheet(self._settings.google_inventory_worksheet)

    def _read_inventory_rows_sync(self) -> list[dict[str, str]]:
        ws = self._inventory_ws()
        self._ensure_worksheet_headers_sync(ws, INVENTORY_HEADERS)
        values = ws.get_all_values()
        normalized = _normalized_rows(values, INVENTORY_HEADERS)
        if not normalized:
            return []
        return normalized[1:]

    def _write_inventory_rows_sync(self, rows: list[dict[str, str]]) -> None:
        ws = self._inventory_ws()
        data = [INVENTORY_HEADERS]
        data.extend([[row.get(header, "") for header in INVENTORY_HEADERS] for row in rows])
        ws.clear()
        ws.update("A1", data, value_input_option="USER_ENTERED")

    def _seed_inventory_sync(self) -> None:
        rows = self._read_inventory_rows_sync()
        now = datetime.now(timezone.utc)
        by_key = {row.get("inventory_key", ""): row for row in rows if row.get("inventory_key")}
        changed = False
        for inventory_key, product_key, login, secret, note in (
            (
                "test-gpt-pro-001",
                "gpt-pro-1m",
                "test-pro@example.com",
                "pro-password-001",
                "Тестовая выдача ChatGPT Pro. VPN в подарок, напиши в поддержку для получения.",
            ),
        ):
            if inventory_key in by_key:
                continue
            spec = get_product_spec(product_key)
            rows.append(
                {
                    "inventory_key": inventory_key,
                    "product_key": product_key,
                    "product_title": spec.title if spec is not None else product_key,
                    "delivery_mode": "auto",
                    "source": "manual_inventory",
                    "status": "available",
                    "order_id": "",
                    "reserved_until": "",
                    "sold_at": "",
                    "access_login": login,
                    "access_secret": secret,
                    "note": note,
                    "updated_at": _dt(now),
                }
            )
            changed = True

        if changed:
            self._write_inventory_rows_sync(rows)

    def _cleanup_expired_inventory_rows(self, rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str], bool]:
        now = datetime.now(timezone.utc)
        expired_order_ids: list[str] = []
        changed = False

        for row in rows:
            status = (row.get("status") or "").strip().lower()
            reserved_until = _parse_dt(row.get("reserved_until", ""))
            if status != "reserved" or reserved_until is None or reserved_until >= now:
                continue
            if row.get("order_id"):
                expired_order_ids.append(row["order_id"])
            row["status"] = "available"
            row["order_id"] = ""
            row["reserved_until"] = ""
            row["updated_at"] = _dt(now)
            changed = True

        return rows, expired_order_ids, changed

    def _cleanup_expired_inventory_reservations_sync(self) -> list[str]:
        rows = self._read_inventory_rows_sync()
        rows, expired_order_ids, changed = self._cleanup_expired_inventory_rows(rows)
        if changed:
            self._write_inventory_rows_sync(rows)
        return list(dict.fromkeys(expired_order_ids))

    def _reserve_inventory_item_sync(
        self,
        order_id: str,
        product_key: str,
        product_title: str,
        reserve_minutes: int,
    ) -> dict[str, str] | None:
        rows = self._read_inventory_rows_sync()
        rows, _, changed = self._cleanup_expired_inventory_rows(rows)
        now = datetime.now(timezone.utc)

        for row in rows:
            if row.get("order_id") == order_id and (row.get("status") or "").strip().lower() == "reserved":
                if changed:
                    self._write_inventory_rows_sync(rows)
                return dict(row)

        reserve_until = now + timedelta(minutes=reserve_minutes)
        target = None
        for row in rows:
            if (row.get("product_key") or "").strip() != product_key:
                continue
            if (row.get("status") or "").strip().lower() != "available":
                continue
            if not (row.get("access_login") or "").strip() or not (row.get("access_secret") or "").strip():
                continue
            target = row
            break

        if target is None:
            if changed:
                self._write_inventory_rows_sync(rows)
            return None

        target["product_title"] = target.get("product_title") or product_title
        target["delivery_mode"] = target.get("delivery_mode") or "auto"
        target["source"] = target.get("source") or "manual_inventory"
        target["status"] = "reserved"
        target["order_id"] = order_id
        target["reserved_until"] = _dt(reserve_until)
        target["updated_at"] = _dt(now)
        self._write_inventory_rows_sync(rows)
        return dict(target)

    def _claim_inventory_item_sync(
        self,
        order_id: str,
        product_key: str,
        product_title: str,
        reserve_minutes: int,
    ) -> dict[str, str] | None:
        rows = self._read_inventory_rows_sync()
        rows, _, _ = self._cleanup_expired_inventory_rows(rows)
        now = datetime.now(timezone.utc)

        target = None
        for row in rows:
            if row.get("order_id") != order_id:
                continue
            if (row.get("status") or "").strip().lower() in {"reserved", "sold"}:
                target = row
                break

        if target is None:
            target = self._reserve_inventory_item_sync(order_id, product_key, product_title, reserve_minutes)
            if target is None:
                return None
            rows = self._read_inventory_rows_sync()
            for row in rows:
                if row.get("inventory_key") == target.get("inventory_key"):
                    target = row
                    break

        if target is None:
            return None

        if (target.get("status") or "").strip().lower() == "sold":
            return dict(target)

        target["product_title"] = target.get("product_title") or product_title
        target["delivery_mode"] = target.get("delivery_mode") or "auto"
        target["source"] = target.get("source") or "manual_inventory"
        target["status"] = "sold"
        target["order_id"] = order_id
        target["reserved_until"] = ""
        target["sold_at"] = _dt(now)
        target["updated_at"] = _dt(now)
        self._write_inventory_rows_sync(rows)
        return dict(target)

    def _release_inventory_reservation_sync(self, order_id: str) -> None:
        rows = self._read_inventory_rows_sync()
        now = datetime.now(timezone.utc)
        changed = False
        for row in rows:
            if row.get("order_id") != order_id:
                continue
            if (row.get("status") or "").strip().lower() != "reserved":
                continue
            row["status"] = "available"
            row["order_id"] = ""
            row["reserved_until"] = ""
            row["updated_at"] = _dt(now)
            changed = True
        if changed:
            self._write_inventory_rows_sync(rows)

    def _worksheet(self, name: str):
        if self._disabled_reason:
            raise GoogleSheetsUnavailableError(self._disabled_reason)
        try:
            spreadsheet = self._client().open_by_key(self._settings.google_sheet_id)
        except (APIError, PermissionError, SpreadsheetNotFound) as exc:
            raise GoogleSheetsUnavailableError(_format_google_access_error(exc, self._settings, self._service_account_email)) from exc
        try:
            return spreadsheet.worksheet(name)
        except WorksheetNotFound:
            return spreadsheet.add_worksheet(name, rows=2000, cols=40)

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

    def _serialize_sale(self, order: Order) -> SheetRow:
        return SheetRow(
            values={
                "sale_id": order.id,
                "paid_at": _dt(order.paid_at),
                "delivered_at": _dt(order.delivered_at),
                "buyer_tg_id": str(order.tg_user_id),
                "buyer_username": order.tg_username or "",
                "customer_email": order.customer_email,
                "product_key": order.product_slug,
                "product_title": order.product_title,
                "amount": str(order.total_price),
                "currency": order.currency,
                "payment_id": order.provider_payment_id or "",
                "payment_status": order.provider_status or "",
                "inventory_key": order.assigned_stock_item_id or "",
            }
        )

    def _ensure_worksheet_headers_sync(self, ws, headers: list[str]) -> None:
        values = ws.get_all_values()
        if not values:
            ws.append_row(headers, value_input_option="USER_ENTERED")
            return
        current_headers = values[0]
        if current_headers == headers:
            return
        normalized = _normalized_rows(values, headers)
        data = [headers]
        data.extend([[row.get(header, "") for header in headers] for row in normalized[1:]])
        ws.clear()
        ws.update("A1", data, value_input_option="USER_ENTERED")


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


def _normalized_rows(values: list[list[str]], headers: list[str]) -> list[dict[str, str]]:
    if not values:
        return []
    current_headers = values[0]
    current_map = {header: idx for idx, header in enumerate(current_headers)}
    rows = [{header: header for header in headers}]
    for row in values[1:]:
        rows.append(
            {
                header: row[current_map[header]] if header in current_map and current_map[header] < len(row) else ""
                for header in headers
            }
        )
    return rows


def _dt(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_dt(raw: str) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
