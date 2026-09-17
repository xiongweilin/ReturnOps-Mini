from __future__ import annotations

import hashlib
import secrets


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(prefix: str = "rtm") -> str:
    return f"{prefix}_{secrets.token_urlsafe(30)}"


def secure_equal(left: str, right: str) -> bool:
    return secrets.compare_digest(left, right)
