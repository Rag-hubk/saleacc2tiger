from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import gspread
from gspread.exceptions import WorksheetNotFound

from saleacc_bot.config import Settings

FREE_STATUSES = {"", "free", "available", "свободен"}
RESERVED_STATUS = "reserved"
SOLD_STATUS = "sold"

INVENTORY_HEADERS = [
    "item_id",
    "product",
    "status",
    "access_login",
    "access_secret",
    "note",
    "sold_to_tg_id",
    "sold_to_username",
    "sold_at",
    "order_id",
    "payment_method",
    "extra_instruction",
    "reserved_for_order_id",
    "reserved_by_tg_id",
    "reserved_until",
    "reserved_at",
]

SALES_HEADERS = [
    "sale_id",
    "order_id",
    "product",
    "quantity",
    "buyer_tg_id",
    "buyer_username",
    "payment_method",
    "total_price",
    "currency",
    "delivered_item_ids",
    "sold_at",
]


@dataclass
class SheetItem:
    row_index: int
    payload: dict[str, str]


class SheetsStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = asyncio.Lock()
        self._gc: gspread.Client | None = None

    async def get_stock_counts(self, product_slugs: list[str]) -> dict[str, int]:
        async with self._lock:
            return await asyncio.to_thread(self._get_stock_counts_sync, product_slugs)

    async def get_inventory_summary(self, product_slugs: list[str]) -> dict[str, dict[str, int]]:
        async with self._lock:
            return await asyncio.to_thread(self._get_inventory_summary_sync, product_slugs)

    async def cleanup_expired_reservations(self) -> list[str]:
        async with self._lock:
            return await asyncio.to_thread(self._cleanup_expired_reservations_sync)

    async def reserve_items(
        self,
        *,
        product_slug: str,
        quantity: int,
        buyer_tg_id: int,
        order_id: str,
        hold_minutes: int,
    ) -> list[dict[str, str]]:
        async with self._lock:
            reserved = await asyncio.to_thread(
                self._reserve_items_sync,
                product_slug,
                quantity,
                buyer_tg_id,
                order_id,
                hold_minutes,
            )
            return [item.payload for item in reserved]

    async def claim_reserved_items(
        self,
        *,
        order_id: str,
        buyer_tg_id: int,
        buyer_username: str | None,
        payment_method: str,
    ) -> list[dict[str, str]]:
        async with self._lock:
            claimed = await asyncio.to_thread(
                self._claim_reserved_items_sync,
                order_id,
                buyer_tg_id,
                buyer_username,
                payment_method,
            )
            return [item.payload for item in claimed]

    async def append_sale_log(
        self,
        *,
        order_id: str,
        product_slug: str,
        quantity: int,
        buyer_tg_id: int,
        buyer_username: str | None,
        payment_method: str,
        total_price: int,
        currency: str,
        delivered_item_ids: list[str],
    ) -> None:
        await asyncio.to_thread(
            self._append_sale_log_sync,
            order_id,
            product_slug,
            quantity,
            buyer_tg_id,
            buyer_username,
            payment_method,
            total_price,
            currency,
            delivered_item_ids,
        )

    async def list_recent_sales(self, limit: int = 15) -> list[dict[str, str]]:
        return await asyncio.to_thread(self._list_recent_sales_sync, limit)

    async def ensure_schema(self) -> None:
        await asyncio.to_thread(self._ensure_schema_sync)

    def _get_stock_counts_sync(self, product_slugs: list[str]) -> dict[str, int]:
        normalized = set(product_slugs)
        result = {slug: 0 for slug in normalized}
        if not normalized:
            return result

        ws = self._inventory_ws()
        values = ws.get_all_values()
        if not values:
            return result

        headers = values[0]
        header_map = self._header_map(headers)
        self._cleanup_expired_reservations_in_memory(ws, values, header_map)

        product_i = self._required_index(header_map, "product")
        status_i = self._required_index(header_map, "status")
        for row in values[1:]:
            product = self._cell(row, product_i)
            if product not in normalized:
                continue
            status = self._cell(row, status_i).strip().lower()
            if status in FREE_STATUSES:
                result[product] = result.get(product, 0) + 1

        return result

    def _get_inventory_summary_sync(self, product_slugs: list[str]) -> dict[str, dict[str, int]]:
        normalized = set(product_slugs)
        result = {
            slug: {"free": 0, "reserved": 0, "sold": 0, "other": 0, "total": 0}
            for slug in normalized
        }
        if not normalized:
            return result

        ws = self._inventory_ws()
        values = ws.get_all_values()
        if not values:
            return result

        headers = values[0]
        header_map = self._header_map(headers)
        self._cleanup_expired_reservations_in_memory(ws, values, header_map)

        product_i = self._required_index(header_map, "product")
        status_i = self._required_index(header_map, "status")
        for row in values[1:]:
            product = self._cell(row, product_i)
            if product not in normalized:
                continue
            status = self._cell(row, status_i).strip().lower()
            bucket = "other"
            if status in FREE_STATUSES:
                bucket = "free"
            elif status == RESERVED_STATUS:
                bucket = "reserved"
            elif status == SOLD_STATUS:
                bucket = "sold"

            result[product][bucket] += 1
            result[product]["total"] += 1

        return result

    def _cleanup_expired_reservations_sync(self) -> list[str]:
        ws = self._inventory_ws()
        values = ws.get_all_values()
        if not values:
            return []
        return self._cleanup_expired_reservations_in_memory(ws, values, self._header_map(values[0]))

    def _reserve_items_sync(
        self,
        product_slug: str,
        quantity: int,
        buyer_tg_id: int,
        order_id: str,
        hold_minutes: int,
    ) -> list[SheetItem]:
        if quantity < 1:
            return []

        ws = self._inventory_ws()
        values = ws.get_all_values()
        if not values:
            return []

        headers = values[0]
        header_map = self._header_map(headers)
        self._cleanup_expired_reservations_in_memory(ws, values, header_map)

        product_i = self._required_index(header_map, "product")
        status_i = self._required_index(header_map, "status")

        reserved_for_order_i = self._required_index(header_map, "reserved_for_order_id")
        reserved_by_tg_i = self._required_index(header_map, "reserved_by_tg_id")
        reserved_until_i = self._required_index(header_map, "reserved_until")
        reserved_at_i = self._required_index(header_map, "reserved_at")

        candidates: list[SheetItem] = []
        for row_idx, row in enumerate(values[1:], start=2):
            if self._cell(row, product_i) != product_slug:
                continue
            status = self._cell(row, status_i).strip().lower()
            if status not in FREE_STATUSES:
                continue
            payload = {header: self._cell(row, col_i) for col_i, header in enumerate(headers)}
            candidates.append(SheetItem(row_idx, payload))
            if len(candidates) >= quantity:
                break

        if len(candidates) < quantity:
            return []

        now = datetime.now(timezone.utc)
        reserved_until = now + timedelta(minutes=hold_minutes)
        now_iso = now.isoformat()
        until_iso = reserved_until.isoformat()
        last_col = _col_to_a1(len(headers))

        for reserved in candidates:
            row_values = ws.row_values(reserved.row_index)
            if len(row_values) < len(headers):
                row_values.extend([""] * (len(headers) - len(row_values)))

            row_values[status_i] = RESERVED_STATUS
            row_values[reserved_for_order_i] = order_id
            row_values[reserved_by_tg_i] = str(buyer_tg_id)
            row_values[reserved_until_i] = until_iso
            row_values[reserved_at_i] = now_iso

            ws.update(
                f"A{reserved.row_index}:{last_col}{reserved.row_index}",
                [row_values],
                value_input_option="USER_ENTERED",
            )

            for i, header in enumerate(headers):
                reserved.payload[header] = row_values[i]

        return candidates

    def _claim_reserved_items_sync(
        self,
        order_id: str,
        buyer_tg_id: int,
        buyer_username: str | None,
        payment_method: str,
    ) -> list[SheetItem]:
        ws = self._inventory_ws()
        values = ws.get_all_values()
        if not values:
            return []

        headers = values[0]
        header_map = self._header_map(headers)
        self._cleanup_expired_reservations_in_memory(ws, values, header_map)

        status_i = self._required_index(header_map, "status")
        reserved_for_order_i = self._required_index(header_map, "reserved_for_order_id")
        reserved_by_tg_i = self._required_index(header_map, "reserved_by_tg_id")
        reserved_until_i = self._required_index(header_map, "reserved_until")
        reserved_at_i = self._required_index(header_map, "reserved_at")

        sold_to_tg_i = self._required_index(header_map, "sold_to_tg_id")
        sold_to_username_i = self._required_index(header_map, "sold_to_username")
        sold_at_i = self._required_index(header_map, "sold_at")
        order_i = self._required_index(header_map, "order_id")
        payment_method_i = self._required_index(header_map, "payment_method")

        candidates: list[SheetItem] = []
        for row_idx, row in enumerate(values[1:], start=2):
            status = self._cell(row, status_i).strip().lower()
            reserved_order = self._cell(row, reserved_for_order_i).strip()
            if status == RESERVED_STATUS and reserved_order == order_id:
                payload = {header: self._cell(row, col_i) for col_i, header in enumerate(headers)}
                candidates.append(SheetItem(row_idx, payload))

        if not candidates:
            return []

        now_iso = datetime.now(timezone.utc).isoformat()
        last_col = _col_to_a1(len(headers))

        for item in candidates:
            row_values = ws.row_values(item.row_index)
            if len(row_values) < len(headers):
                row_values.extend([""] * (len(headers) - len(row_values)))

            row_values[status_i] = SOLD_STATUS
            row_values[reserved_for_order_i] = ""
            row_values[reserved_by_tg_i] = ""
            row_values[reserved_until_i] = ""
            row_values[reserved_at_i] = ""

            row_values[sold_to_tg_i] = str(buyer_tg_id)
            row_values[sold_to_username_i] = buyer_username or ""
            row_values[sold_at_i] = now_iso
            row_values[order_i] = order_id
            row_values[payment_method_i] = payment_method

            ws.update(
                f"A{item.row_index}:{last_col}{item.row_index}",
                [row_values],
                value_input_option="USER_ENTERED",
            )

            for i, header in enumerate(headers):
                item.payload[header] = row_values[i]

        return candidates

    def _cleanup_expired_reservations_in_memory(
        self,
        ws: gspread.Worksheet,
        values: list[list[str]],
        header_map: dict[str, int],
    ) -> list[str]:
        required = {"status", "reserved_for_order_id", "reserved_until"}
        if not required.issubset(header_map):
            return []

        status_i = header_map["status"]
        reserved_for_order_i = header_map["reserved_for_order_id"]
        reserved_by_tg_i = header_map.get("reserved_by_tg_id")
        reserved_until_i = header_map["reserved_until"]
        reserved_at_i = header_map.get("reserved_at")

        now = datetime.now(timezone.utc)
        last_col = _col_to_a1(len(values[0]))
        expired_orders: set[str] = set()

        for row_idx, row in enumerate(values[1:], start=2):
            status = self._cell(row, status_i).strip().lower()
            if status != RESERVED_STATUS:
                continue

            until_raw = self._cell(row, reserved_until_i).strip()
            until = _parse_datetime_utc(until_raw)
            if until is None or until >= now:
                continue

            reserved_order = self._cell(row, reserved_for_order_i).strip()
            if reserved_order:
                expired_orders.add(reserved_order)

            row_values = ws.row_values(row_idx)
            if len(row_values) < len(values[0]):
                row_values.extend([""] * (len(values[0]) - len(row_values)))

            row_values[status_i] = "free"
            row_values[reserved_for_order_i] = ""
            if reserved_by_tg_i is not None:
                row_values[reserved_by_tg_i] = ""
            row_values[reserved_until_i] = ""
            if reserved_at_i is not None:
                row_values[reserved_at_i] = ""

            ws.update(f"A{row_idx}:{last_col}{row_idx}", [row_values], value_input_option="USER_ENTERED")

            row_copy = values[row_idx - 1]
            if len(row_copy) < len(values[0]):
                row_copy.extend([""] * (len(values[0]) - len(row_copy)))
            row_copy[status_i] = "free"
            row_copy[reserved_for_order_i] = ""
            if reserved_by_tg_i is not None:
                row_copy[reserved_by_tg_i] = ""
            row_copy[reserved_until_i] = ""
            if reserved_at_i is not None:
                row_copy[reserved_at_i] = ""

        return list(expired_orders)

    def _append_sale_log_sync(
        self,
        order_id: str,
        product_slug: str,
        quantity: int,
        buyer_tg_id: int,
        buyer_username: str | None,
        payment_method: str,
        total_price: int,
        currency: str,
        delivered_item_ids: list[str],
    ) -> None:
        ws = self._sales_ws()
        values = ws.get_all_values()
        if not values:
            ws.append_row(SALES_HEADERS)
            headers = SALES_HEADERS
        else:
            headers = values[0]

        header_map = self._header_map(headers)
        row = [""] * len(headers)
        payload = {
            "sale_id": str(uuid4()),
            "order_id": order_id,
            "product": product_slug,
            "quantity": str(quantity),
            "buyer_tg_id": str(buyer_tg_id),
            "buyer_username": buyer_username or "",
            "payment_method": payment_method,
            "total_price": str(total_price),
            "currency": currency,
            "delivered_item_ids": ",".join(delivered_item_ids),
            "sold_at": datetime.now(timezone.utc).isoformat(),
        }

        for key, value in payload.items():
            idx = header_map.get(key)
            if idx is not None:
                row[idx] = value

        ws.append_row(row, value_input_option="USER_ENTERED")

    def _list_recent_sales_sync(self, limit: int) -> list[dict[str, str]]:
        ws = self._sales_ws()
        values = ws.get_all_values()
        if len(values) <= 1:
            return []

        headers = values[0]
        rows = values[1:]
        output: list[dict[str, str]] = []

        for row in reversed(rows):
            payload = {header: self._cell(row, i) for i, header in enumerate(headers)}
            output.append(payload)
            if len(output) >= limit:
                break

        return output

    def _ensure_schema_sync(self) -> None:
        spreadsheet = self._spreadsheet()
        self._ensure_worksheet_headers(spreadsheet, self._settings.google_inventory_worksheet, INVENTORY_HEADERS)
        self._ensure_worksheet_headers(spreadsheet, self._settings.google_sales_worksheet, SALES_HEADERS)

    def _ensure_worksheet_headers(self, spreadsheet: gspread.Spreadsheet, title: str, headers: list[str]) -> None:
        try:
            ws = spreadsheet.worksheet(title)
        except WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=title, rows=2000, cols=max(30, len(headers) + 5))

        values = ws.get_all_values()
        if not values:
            ws.append_row(headers)
            return

        current_headers = [h.strip() for h in values[0]]
        merged_headers = current_headers[:]
        for header in headers:
            if header not in merged_headers:
                merged_headers.append(header)

        if merged_headers != current_headers:
            ws.update(
                f"A1:{_col_to_a1(len(merged_headers))}1",
                [merged_headers],
                value_input_option="RAW",
            )

    def _inventory_ws(self) -> gspread.Worksheet:
        return self._spreadsheet().worksheet(self._settings.google_inventory_worksheet)

    def _sales_ws(self) -> gspread.Worksheet:
        return self._spreadsheet().worksheet(self._settings.google_sales_worksheet)

    def _spreadsheet(self) -> gspread.Spreadsheet:
        if self._gc is None:
            key_path = Path(self._settings.google_service_account_file)
            if not key_path.exists():
                raise RuntimeError(f"Google service account file not found: {key_path}")
            self._gc = gspread.service_account(filename=str(key_path))
        return self._gc.open_by_key(self._settings.google_sheet_id)

    @staticmethod
    def _header_map(headers: list[str]) -> dict[str, int]:
        return {name.strip(): idx for idx, name in enumerate(headers)}

    @staticmethod
    def _required_index(header_map: dict[str, int], key: str) -> int:
        if key not in header_map:
            raise RuntimeError(f"Worksheet is missing required column: {key}")
        return header_map[key]

    @staticmethod
    def _cell(row: list[str], index: int) -> str:
        if index < len(row):
            return row[index]
        return ""


def _parse_datetime_utc(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _col_to_a1(index: int) -> str:
    if index < 1:
        raise ValueError("Column index must be >= 1")
    letters = ""
    current = index
    while current:
        current, rem = divmod(current - 1, 26)
        letters = chr(65 + rem) + letters
    return letters
