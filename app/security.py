"""Security utilities (cross-cutting layer): PIN & password hashing.

PINs and staff passwords are stored only as one-way bcrypt hashes. There is no
way to recover a PIN — a forgotten PIN is reset, never revealed.
"""
import re

import bcrypt

from app.config import settings

# bcrypt hashes at most 72 bytes of input; PINs and staff passwords are far
# shorter, but we truncate defensively so an over-long password never errors.
_MAX_BYTES = 72


def _hash(secret: str) -> str:
    return bcrypt.hashpw(secret.encode("utf-8")[:_MAX_BYTES], bcrypt.gensalt()).decode("utf-8")


def _verify(secret: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    return bcrypt.checkpw(secret.encode("utf-8")[:_MAX_BYTES], hashed.encode("utf-8"))


def is_valid_pin_format(pin: str) -> bool:
    """A PIN must be exactly PIN_LENGTH digits (default 4)."""
    return bool(re.fullmatch(rf"\d{{{settings.pin_length}}}", pin or ""))


def is_weak_pin(pin: str) -> bool:
    """Reject trivially guessable PINs (all-same digits, simple sequences)."""
    if len(set(pin)) == 1:  # 0000, 1111, ...
        return True
    ascending = "".join(str(d % 10) for d in range(int(pin[0]), int(pin[0]) + len(pin)))
    descending = "".join(str(d % 10) for d in range(int(pin[0]), int(pin[0]) - len(pin), -1))
    return pin in (ascending, descending)


def hash_pin(pin: str) -> str:
    return _hash(pin)


def verify_pin(pin: str, pin_hash: str | None) -> bool:
    return _verify(pin, pin_hash)


def hash_password(password: str) -> str:
    return _hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _verify(password, password_hash)
