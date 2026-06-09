"""Fernet-encrypted secret store for AI profile sk values.

``sk`` values are persisted encrypted at rest through a thin encryption layer:

  * on write, the plaintext sk is encrypted with Fernet (AES128-CBC + HMAC)
    and the resulting ciphertext is stored in a new column
    ``ai_profiles.sk_ciphertext``;
  * on read (via the dispatcher-only ``/secret`` endpoint), the
    ciphertext is decrypted back to plaintext just before the response
    leaves the server;
  * the plaintext ``sk`` column is retained only as a write-through
    compatibility field for the existing API shape.

The encryption key is loaded from ``CAIRN_JWT_SECRET`` (falling back to
``CAIRN_SECRETS_KEY``) so operators do not need a third secret. Fernet
requires a 32-byte url-safe base64 key; we derive it deterministically
from the secret with SHA-256, which keeps the operator-facing key
format operator-friendly (a 48-byte url-safe token) while giving
Fernet the bytes it needs.

If the key changes, ``decrypt_secret`` raises ``SecretDecryptionError``
so callers can surface "sk values must be re-entered" instead of
returning gibberish.
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


_RAW_KEY_ENV = "CAIRN_JWT_SECRET"
_FALLBACK_KEY_ENV = "CAIRN_SECRETS_KEY"
_PLACEHOLDER_PREFIX = "enc:v1:"


class SecretError(RuntimeError):
    """Base class for encryption / decryption failures."""


class SecretDecryptionError(SecretError):
    """Raised when a stored ciphertext cannot be decrypted.

    Typical cause: the operator rotated ``CAIRN_JWT_SECRET`` after
    writing the sk. Recovery is to clear and re-enter the sk on the
    affected profile.
    """


def _derive_fernet_key() -> bytes:
    raw = os.environ.get(_RAW_KEY_ENV) or os.environ.get(_FALLBACK_KEY_ENV)
    if not raw:
        raise SecretError(
            f"{_RAW_KEY_ENV} (or {_FALLBACK_KEY_ENV}) is not set; cannot encrypt secrets"
        )
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_derive_fernet_key())


def encrypt_secret(plaintext: str) -> str:
    """Encrypt ``plaintext`` and return a ``enc:v1:<base64-ciphertext>`` token."""
    if not plaintext:
        return ""
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return f"{_PLACEHOLDER_PREFIX}{token}"


def decrypt_secret(stored: str) -> str:
    """Inverse of :func:`encrypt_secret`.

    Empty input is returned as-is so legacy empty rows do not require
    any special handling. Anything that does not start with
    ``enc:v1:`` is treated as plaintext (legacy support during the
    migration window) - this is intentional so a partial rollout does
    not brick the catalog.
    """
    if not stored:
        return ""
    if not stored.startswith(_PLACEHOLDER_PREFIX):
        return stored
    token = stored[len(_PLACEHOLDER_PREFIX):]
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptionError(
            "sk ciphertext cannot be decrypted with the current key; "
            "re-enter the sk on the affected profile"
        ) from exc


def is_encrypted(stored: str) -> bool:
    return bool(stored) and stored.startswith(_PLACEHOLDER_PREFIX)
