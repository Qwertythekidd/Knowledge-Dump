from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError


class CredentialSecurity:
    def __init__(self, token_pepper: str) -> None:
        self._password_hasher = PasswordHasher()
        self._pepper = token_pepper.encode("utf-8")

    def hash_password(self, password: str) -> str:
        self.validate_password(password)
        return self._password_hasher.hash(password)

    def verify_password(self, password_hash: str, password: str) -> tuple[bool, str | None]:
        try:
            verified = self._password_hasher.verify(password_hash, password)
        except (InvalidHashError, VerifyMismatchError, VerificationError):
            return False, None
        if not verified:
            return False, None
        replacement = self._password_hasher.hash(password) if self._password_hasher.check_needs_rehash(password_hash) else None
        return True, replacement

    def new_token(self) -> str:
        return secrets.token_urlsafe(48)

    def token_hash(self, token: str) -> str:
        return hmac.new(self._pepper, token.encode("utf-8"), hashlib.sha256).hexdigest()

    def token_matches(self, expected_hash: str, token: str) -> bool:
        return hmac.compare_digest(expected_hash, self.token_hash(token))

    @staticmethod
    def validate_password(password: str) -> None:
        if len(password) < 12:
            raise ValueError("password_too_short")
        if len(password.encode("utf-8")) > 1024:
            raise ValueError("password_too_long")
