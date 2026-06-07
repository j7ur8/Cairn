"""Bcrypt password hashing.

Single source of truth for hashing and verification. Uses ``bcrypt`` directly
(no passlib indirection) to avoid the passlib 1.7.4 / bcrypt 4.x compatibility
churn that bit us in 2024. Stored hashes are self-describing (``$2b$...``)
so the cost factor can be raised in place without code changes.
"""
from __future__ import annotations

import bcrypt


_BCRYPT_ROUNDS = 12  # ~250ms on a modern server; tunable via env in a later pass.


def hash_password(plaintext: str) -> str:
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    digest = bcrypt.hashpw(plaintext.encode("utf-8"), salt)
    return digest.decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    if not plaintext or not hashed:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
