"""The person's own Telegram key and session, kept in the macOS Keychain and nowhere else."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from . import paths
from .errors import UserError


@dataclass(frozen=True)
class ApiKey:
    api_id: int
    api_hash: str

    def masked(self) -> str:
        return f"{self.api_id} · {self.api_hash[:4]}…{self.api_hash[-4:]}"


class Vault:
    def __init__(self, service: Optional[str] = None):
        self.service = service or paths.keychain_service()

    def _get(self, name: str) -> str:
        try:
            return keyring.get_password(self.service, name) or ""
        except KeyringError as exc:
            raise UserError("ما قدرنا نقرا من الـ Keychain.", "keychain") from exc

    def _set(self, name: str, value: str) -> None:
        try:
            keyring.set_password(self.service, name, value)
        except KeyringError as exc:
            raise UserError("ما قدرنا نحفظ بالـ Keychain.", "keychain") from exc

    def _delete(self, name: str) -> None:
        try:
            keyring.delete_password(self.service, name)
        except (PasswordDeleteError, KeyringError):
            pass

    def api_key(self) -> Optional[ApiKey]:
        api_id, api_hash = self._get("api_id"), self._get("api_hash")
        if not api_id.isdigit() or not api_hash:
            return None
        return ApiKey(int(api_id), api_hash)

    def save_api_key(self, key: ApiKey) -> None:
        self._set("api_id", str(key.api_id))
        self._set("api_hash", key.api_hash)

    def clear_api_key(self) -> None:
        self._delete("api_id")
        self._delete("api_hash")
        self.clear_session()

    def session(self) -> str:
        return self._get("session")

    def save_session(self, value: str) -> None:
        if value:
            self._set("session", value)

    def clear_session(self) -> None:
        self._delete("session")
