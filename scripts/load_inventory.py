#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import gspread
from dotenv import load_dotenv

from saleacc_bot.config import get_settings
from saleacc_bot.services.sheets_store import INVENTORY_HEADERS

load_dotenv()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load inventory rows from CSV into Google Sheets")
    parser.add_argument("--product", required=True, help="Product slug, e.g. gpt-pro-1m")
    parser.add_argument("--file", required=True, help="Path to CSV file")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()

    csv_path = Path(args.file)
    if not csv_path.exists():
        raise SystemExit(f"CSV file not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        source_rows = list(reader)

    if not source_rows:
        raise SystemExit("CSV file has no rows")

    gc = gspread.service_account(filename=settings.google_service_account_file)
    ws = gc.open_by_key(settings.google_sheet_id).worksheet(settings.google_inventory_worksheet)

    existing = ws.get_all_values()
    if not existing:
        ws.append_row(INVENTORY_HEADERS)

    payload_rows: list[list[str]] = []
    for idx, row in enumerate(source_rows, start=1):
        item_id = row.get("item_id") or f"{args.product}-{idx}"
        prepared = {key: "" for key in INVENTORY_HEADERS}
        prepared["item_id"] = item_id
        prepared["product"] = args.product
        prepared["status"] = "free"
        prepared["supplier_purchased_at"] = row.get("supplier_purchased_at", row.get("purchased_at", ""))
        prepared["access_login"] = row.get("access_login", row.get("email", ""))
        prepared["access_secret"] = row.get("access_secret", row.get("password", ""))
        prepared["note"] = row.get("note", "")
        prepared["extra_instruction"] = row.get("extra_instruction", row.get("instruction", ""))
        payload_rows.append([prepared[key] for key in INVENTORY_HEADERS])

    ws.append_rows(payload_rows, value_input_option="USER_ENTERED")
    print(f"Inserted rows: {len(payload_rows)}")


if __name__ == "__main__":
    main()
