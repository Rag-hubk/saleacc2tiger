from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class InventoryCipher:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key)

    def encrypt_payload(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._fernet.encrypt(raw).decode("utf-8")

    def decrypt_payload(self, ciphertext: str) -> dict[str, Any]:
        try:
            raw = self._fernet.decrypt(ciphertext.encode("utf-8"))
        except InvalidToken as exc:
            raise ValueError("Cannot decrypt inventory payload") from exc
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Inventory payload must be an object")
        return payload
