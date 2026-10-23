"""Verschlüsselung gespeicherter Geheimnisse und Passwort-Hashes."""
import base64
import hashlib
import hmac
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken

from .config import config

_fernet: Fernet | None = None


def fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = config.secret_key
        if not key:
            if not config.dev:
                raise RuntimeError("HAUSKI_SECRET_KEY fehlt in /etc/haus-ki/haus-ki.env")
            key = base64.urlsafe_b64encode(hashlib.sha256(b"haus-ki-dev").digest()).decode()
        _fernet = Fernet(key.encode())
    return _fernet


def encrypt(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str:
    if not value:
        return ""
    try:
        return fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return ""


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=2**26)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        # Gleiche Laufzeit wie ein echter Vergleich, damit Benutzernamen nicht erratbar sind.
        hashlib.scrypt(password.encode(), salt=b"0" * 16, n=2**15, r=8, p=1, maxmem=2**26)
        return False
    _, salt_b64, digest_b64 = stored.split("$")
    digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=2**15, r=8, p=1, maxmem=2**26)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
