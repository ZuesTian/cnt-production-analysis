from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Any

from config import Settings


PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{2,32}$")


class AuthConfigurationError(RuntimeError):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidSessionError(Exception):
    pass


class LoginRateLimitedError(Exception):
    def __init__(self, retry_after_seconds: int):
        super().__init__("login rate limited")
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class AuthUser:
    username: str
    display_name: str
    password_hash: str

    def public_dict(self) -> dict[str, str]:
        return {"username": self.username, "display_name": self.display_name}


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(
    password: str,
    *,
    salt: bytes | None = None,
    iterations: int = PASSWORD_ITERATIONS,
) -> str:
    if not password:
        raise ValueError("password must not be empty")
    if iterations < 100_000:
        raise ValueError("password hashing iterations are too low")
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), actual_salt, iterations)
    return f"{PASSWORD_ALGORITHM}${iterations}${_b64encode(actual_salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        iterations = int(iterations_text)
        if algorithm != PASSWORD_ALGORITHM or not 100_000 <= iterations <= 2_000_000:
            return False
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
        if not 8 <= len(salt) <= 64 or len(expected) != 32:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        return False
    return hmac.compare_digest(actual, expected)


def password_hash_is_valid(encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        iterations = int(iterations_text)
        salt = _b64decode(salt_text)
        digest = _b64decode(digest_text)
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        return False
    return (
        algorithm == PASSWORD_ALGORITHM
        and 100_000 <= iterations <= 2_000_000
        and 8 <= len(salt) <= 64
        and len(digest) == 32
    )


class LoginRateLimiter:
    def __init__(self, attempts: int = 5, window_seconds: int = 10 * 60):
        self.attempts = attempts
        self.window_seconds = window_seconds
        self.events: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    def _trim(self, queue: deque[float], now: float) -> None:
        while queue and now - queue[0] >= self.window_seconds:
            queue.popleft()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self.lock:
            queue = self.events[key]
            self._trim(queue, now)
            if len(queue) >= self.attempts:
                retry_after = max(1, int(self.window_seconds - (now - queue[0])) + 1)
                raise LoginRateLimitedError(retry_after)

    def failed(self, key: str) -> None:
        now = time.monotonic()
        with self.lock:
            queue = self.events[key]
            self._trim(queue, now)
            queue.append(now)

    def succeeded(self, key: str) -> None:
        with self.lock:
            self.events.pop(key, None)


class AuthManager:
    def __init__(
        self,
        users: list[AuthUser],
        secret: str,
        token_ttl_seconds: int,
        *,
        login_limiter: LoginRateLimiter | None = None,
    ):
        if len(secret.encode("utf-8")) < 32:
            raise AuthConfigurationError("CNT_AUTH_SECRET must contain at least 32 bytes")
        if not users:
            raise AuthConfigurationError("at least one authentication user is required")
        self.users = {user.username.lower(): user for user in users}
        if len(self.users) != len(users):
            raise AuthConfigurationError("authentication usernames must be unique")
        self.secret = secret.encode("utf-8")
        self.token_ttl_seconds = token_ttl_seconds
        self.login_limiter = login_limiter or LoginRateLimiter()
        self._dummy_password_hash = users[0].password_hash

    @classmethod
    def from_settings(cls, settings: Settings) -> AuthManager | None:
        configured = bool(settings.auth_users_b64 or settings.auth_secret)
        if not configured:
            return None
        if not settings.auth_users_b64 or not settings.auth_secret:
            raise AuthConfigurationError(
                "CNT_AUTH_USERS_B64 and CNT_AUTH_SECRET must be configured together"
            )
        try:
            raw_users = json.loads(_b64decode(settings.auth_users_b64).decode("utf-8"))
        except (ValueError, UnicodeError, binascii.Error, json.JSONDecodeError) as exc:
            raise AuthConfigurationError("CNT_AUTH_USERS_B64 is invalid") from exc
        if not isinstance(raw_users, list):
            raise AuthConfigurationError("CNT_AUTH_USERS_B64 must encode a JSON array")
        users = [cls._parse_user(item) for item in raw_users]
        return cls(users, settings.auth_secret, settings.auth_token_ttl_seconds)

    @staticmethod
    def _parse_user(value: Any) -> AuthUser:
        if not isinstance(value, dict):
            raise AuthConfigurationError("authentication user entries must be objects")
        username = value.get("username")
        display_name = value.get("display_name")
        password_hash = value.get("password_hash")
        if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
            raise AuthConfigurationError("authentication username is invalid")
        if not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 64:
            raise AuthConfigurationError("authentication display name is invalid")
        if not isinstance(password_hash, str) or not password_hash_is_valid(password_hash):
            raise AuthConfigurationError("authentication password hash is invalid")
        return AuthUser(username=username.lower(), display_name=display_name.strip(), password_hash=password_hash)

    @staticmethod
    def _rate_key(client_ip: str) -> str:
        # Limit before password hashing and aggregate unknown usernames by source IP,
        # so random usernames cannot create unbounded limiter entries or CPU work.
        return client_ip[:128]

    def authenticate(self, username: str, password: str, client_ip: str) -> AuthUser:
        normalized = username.strip().lower()
        key = self._rate_key(client_ip)
        self.login_limiter.check(key)
        user = self.users.get(normalized)
        password_matches = verify_password(password, user.password_hash if user else self._dummy_password_hash)
        if user is None or not password_matches:
            self.login_limiter.failed(key)
            raise InvalidCredentialsError
        self.login_limiter.succeeded(key)
        return user

    def issue_token(self, user: AuthUser, *, now: int | None = None) -> tuple[str, int]:
        issued_at = int(time.time()) if now is None else now
        payload = {
            "sub": user.username,
            "iat": issued_at,
            "exp": issued_at + self.token_ttl_seconds,
            "jti": secrets.token_urlsafe(12),
        }
        encoded_payload = _b64encode(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signed = f"v1.{encoded_payload}"
        signature = _b64encode(hmac.new(self.secret, signed.encode("ascii"), hashlib.sha256).digest())
        return f"{signed}.{signature}", self.token_ttl_seconds

    def verify_token(self, token: str, *, now: int | None = None) -> AuthUser:
        try:
            version, encoded_payload, supplied_signature = token.split(".", 2)
            if version != "v1":
                raise InvalidSessionError
            signed = f"{version}.{encoded_payload}"
            expected_signature = _b64encode(
                hmac.new(self.secret, signed.encode("ascii"), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(supplied_signature, expected_signature):
                raise InvalidSessionError
            payload = json.loads(_b64decode(encoded_payload).decode("utf-8"))
            username = payload["sub"]
            issued_at = int(payload["iat"])
            expires_at = int(payload["exp"])
            current = int(time.time()) if now is None else now
            if not isinstance(username, str) or issued_at > current + 60 or expires_at <= current:
                raise InvalidSessionError
            if expires_at - issued_at != self.token_ttl_seconds:
                raise InvalidSessionError
            user = self.users.get(username.lower())
            if user is None:
                raise InvalidSessionError
            return user
        except (KeyError, TypeError, ValueError, UnicodeError, binascii.Error, json.JSONDecodeError) as exc:
            raise InvalidSessionError from exc
