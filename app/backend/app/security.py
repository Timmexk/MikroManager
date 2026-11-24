"""Credential encryption (Fernet), password hashing (scrypt) and sessions."""
import hashlib
import hmac
import os
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken

from . import db
from .config import DATA_DIR

_fernet: Fernet | None = None
SESSION_TTL = 30 * 86400


def init() -> None:
    """Load or create the key that encrypts router passwords at rest.

    The key lives next to the database. Losing it makes stored device
    passwords unrecoverable, so it belongs in the same backup as the db.
    """
    global _fernet
    key_file = DATA_DIR / "secret.key"
    if not key_file.exists():
        key_file.write_bytes(Fernet.generate_key())
        os.chmod(key_file, 0o600)
    _fernet = Fernet(key_file.read_bytes().strip())


def encrypt(text: str) -> str:
    return _fernet.encrypt(text.encode()).decode() if text else ""


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        return ""


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def create_user(username: str, password: str) -> int:
    salt = secrets.token_bytes(16)
    return db.x("INSERT INTO users (username, pw_hash, salt) VALUES (?,?,?)", username, _hash(password, salt), salt)


def set_password(user_id: int, password: str) -> None:
    salt = secrets.token_bytes(16)
    db.x("UPDATE users SET pw_hash=?, salt=? WHERE id=?", _hash(password, salt), salt, user_id)
    db.x("DELETE FROM sessions WHERE user_id=?", user_id)


def check_login(username: str, password: str) -> dict | None:
    user = db.q1("SELECT * FROM users WHERE username=?", username)
    if not user:
        _hash(password, b"0" * 16)  # keep timing similar for unknown users
        return None
    return user if hmac.compare_digest(_hash(password, user["salt"]), user["pw_hash"]) else None


def new_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.x("DELETE FROM sessions WHERE expires < ?", time.time())
    db.x("INSERT INTO sessions (token, user_id, expires) VALUES (?,?,?)", token, user_id, time.time() + SESSION_TTL)
    return token


def session_user(token: str | None) -> dict | None:
    if not token:
        return None
    return db.q1("SELECT u.id, u.username FROM sessions s JOIN users u ON u.id = s.user_id "
                 "WHERE s.token=? AND s.expires > ?", token, time.time())


def end_session(token: str | None) -> None:
    if token:
        db.x("DELETE FROM sessions WHERE token=?", token)
