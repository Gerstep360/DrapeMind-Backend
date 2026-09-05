from datetime import datetime, timedelta, timezone
from typing import Any
from jose import JWTError, jwt
import bcrypt

# Compatibilidad de passlib con versiones modernas de bcrypt (>= 4.1.0 en Python 3.12 - 3.14)
if not hasattr(bcrypt, "__about__"):
    class _BcryptAbout:
        __version__ = getattr(bcrypt, "__version__", "4.0.1")
    bcrypt.__about__ = _BcryptAbout()

from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(plain_password, password_hash)
    except Exception:
        # Fallback nativo directo con bcrypt si passlib tiene conflicto
        try:
            return bcrypt.checkpw(
                plain_password.encode("utf-8")[:72],
                password_hash.encode("utf-8")
            )
        except Exception:
            return False


def hash_password(password: str) -> str:
    truncated = password.encode("utf-8")[:72]
    try:
        return pwd_context.hash(truncated.decode("utf-8", errors="ignore"))
    except Exception:
        # Fallback nativo directo con bcrypt
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(truncated, salt).decode("utf-8")


get_password_hash = hash_password


def create_access_token(subject: int | str, role: str) -> tuple[str, int]:
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject), "role": role, "type": "access", "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM), expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Token invalido o expirado") from exc
    if payload.get("type") != "access" or not payload.get("sub"):
        raise ValueError("Tipo de token invalido")
    return payload


def decode_token(token: str) -> int | None:
    try:
        data = decode_access_token(token)
        return int(data["sub"])
    except Exception:
        return None

