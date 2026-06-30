"""Authentication: password hashing, session login, current-user dependency."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, select

from .db import User, get_session

_PBKDF2_ROUNDS = 240_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds_text, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds_text)
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def create_user(session: Session, username: str, password: str) -> User:
    user = User(username=username, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    """FastAPI dependency that resolves the logged-in user or 401s."""

    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = session.get(User, user_id)
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def get_optional_user(request: Request, session: Session = Depends(get_session)) -> User | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    return session.get(User, user_id)


class LoginRequired(Exception):
    """Raised by HTML routes when no session exists; handled as a redirect."""


def web_user(request: Request, session: Session = Depends(get_session)) -> User:
    """Dependency for HTML pages: resolve the user or trigger a login redirect."""

    user_id = request.session.get("user_id")
    if user_id is not None:
        user = session.get(User, user_id)
        if user is not None:
            return user
    raise LoginRequired()
