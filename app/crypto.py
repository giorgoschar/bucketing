"""Field-level encryption for secrets stored in the database (TOTP seeds).

Ciphertext is prefixed with ``enc:`` so rows written before encryption existed
(plain base32 secrets) keep working: ``decrypt_str`` returns any value without
the prefix unchanged, and callers re-encrypt lazily.
"""
import base64
import logging
from functools import lru_cache

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings

logger = logging.getLogger(__name__)

PREFIX = "enc:"
_HKDF_SALT = b"expenses.field-encryption.v1.salt"
_HKDF_INFO = b"expenses.field-encryption.v1.fernet-key"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    if settings.field_encryption_key:
        return Fernet(settings.field_encryption_key.encode())
    logger.warning(
        "FIELD_ENCRYPTION_KEY is not set; deriving the field-encryption key from "
        "APP_SECRET_KEY. Changing APP_SECRET_KEY will make stored TOTP secrets unreadable."
    )
    raw = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=_HKDF_SALT, info=_HKDF_INFO
    ).derive(settings.app_secret_key.encode())
    return Fernet(base64.urlsafe_b64encode(raw))


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt_str(s: str) -> str:
    return PREFIX + _fernet().encrypt(s.encode()).decode()


def decrypt_str(s: str) -> str:
    if not s.startswith(PREFIX):
        return s  # legacy plaintext value
    return _fernet().decrypt(s[len(PREFIX):].encode()).decode()
