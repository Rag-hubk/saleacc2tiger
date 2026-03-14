from __future__ import annotations

from urllib.parse import urlparse


def normalize_public_url(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.startswith("@") and len(raw) > 1:
        return f"https://t.me/{raw[1:]}"
    if raw.startswith("t.me/") or raw.startswith("telegram.me/"):
        return f"https://{raw}"
    return raw


def is_valid_http_url(value: str | None) -> bool:
    raw = (value or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
