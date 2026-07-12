"""
security.py - Utilitas keamanan untuk hashing password dan pembuatan JWT token.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Union
import bcrypt
import jwt

from backend.core.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Memverifikasi kesamaan antara password plain text dan hash password di DB.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """
    Melakukan hash pada plain password text menggunakan bcrypt.
    """
    # bcrypt.hashpw mengembalikan bytes, jadi kita decode ke string untuk disimpan di DB
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def create_access_token(
    data: dict, expires_delta: Union[timedelta, None] = None
) -> str:
    """
    Membuat token JWT terenkripsi dengan payload data yang diberikan.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.access_token_expire_minutes
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )
    return encoded_jwt
