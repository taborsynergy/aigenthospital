"""
JWT token management for clinic users.
"""
from datetime import datetime, timedelta
import jwt
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.config import settings

security = HTTPBearer()


def _signing_key() -> str:
    """JWT signing key — explicit jwt_secret_key, else fall back to admin_password."""
    return settings.jwt_secret_key or settings.admin_password


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token for clinic users.

    Args:
        data: Dictionary with user info (user_id, clinic_id, role, etc.)
        expires_delta: Token expiration time (default: 30 days)

    Returns:
        Encoded JWT token
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=30)

    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(
        to_encode,
        _signing_key(),
        algorithm="HS256"
    )
    return encoded_jwt


def verify_access_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> int:
    """
    Verify JWT token and return user_id.

    Used as a dependency in FastAPI routes.

    Args:
        credentials: HTTP Bearer token from request

    Returns:
        user_id from token payload

    Raises:
        HTTPException: 401 if token is invalid or expired
    """
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            _signing_key(),
            algorithms=["HS256"]
        )
        user_id: int = payload.get("user_id")

        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )

        return user_id

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired"
        )

    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
