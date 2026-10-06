"""Field-level encryption for secrets stored in the database (TOTP seeds).

Ciphertext is prefixed with ``enc:`` so rows written before encryption existed
(plain base32 secrets) keep working: ``decrypt_str`` returns any value without
the prefix unchanged, and callers re-encrypt lazily.
"""
import base64
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

logger = logging.getLogger(__name__)

PREFIX = "enc:"
_HKDF_SALT = b"expenses.field-encryption.v1.salt"
_HKDF_INFO = b"expenses.field-encryption.v1.fernet-key"


_warned = False


def _derived() -> Fernet:
    raw = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=_HKDF_SALT, info=_HKDF_INFO
    ).derive(settings.app_secret_key.encode())
    return Fernet(base64.urlsafe_b64encode(raw))


def _primary() -> Fernet:
    """Key used for all new encryption: FIELD_ENCRYPTION_KEY, else the derived key."""
    global _warned
    if settings.field_encryption_key:
        return Fernet(settings.field_encryption_key.encode())
    if not _warned:
        _warned = True
        logger.warning(
            "FIELD_ENCRYPTION_KEY is not set; deriving the field-encryption key from "
            "APP_SECRET_KEY. Changing APP_SECRET_KEY will make stored TOTP secrets unreadable."
        )
    return _derived()


def _multi() -> MultiFernet:
    """Decrypts with the primary key, then the derived key.

    The derived key stays accepted so secrets encrypted before FIELD_ENCRYPTION_KEY
    was set remain readable (and get re-encrypted under the primary key).
    """
    keys = [_primary()]
    if settings.field_encryption_key:
        keys.append(_derived())
    return MultiFernet(keys)


def needs_rotation(value: str | None) -> bool:
    """True if `value` is plaintext or encrypted under a non-primary key."""
    if not value or not value.startswith(PREFIX):
        return bool(value)
    try:
        _primary().decrypt(value[len(PREFIX):].encode())
        return False
    except InvalidToken:
        return True


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt_str(s: str) -> str:
    return PREFIX + _primary().encrypt(s.encode()).decode()


def decrypt_str(s: str) -> str:
    if not s.startswith(PREFIX):
        return s  # legacy plaintext value
    return _multi().decrypt(s[len(PREFIX):].encode()).decode()
