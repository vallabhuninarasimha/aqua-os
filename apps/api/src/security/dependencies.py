"""FastAPI dependencies enforcing bearer authentication, RBAC and tenant isolation."""
from typing import Callable, Optional

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.src.dependencies import get_db_session
from apps.api.src.security.interfaces import IIdentityProvider
from apps.api.src.security.jwt_provider import LocalJWTIdentityProvider
from apps.api.src.security.models import Permission, UserIdentity


def get_identity_provider(session: Session = Depends(get_db_session)) -> IIdentityProvider:
    return LocalJWTIdentityProvider(session)


def get_current_user(
    authorization: Optional[str] = Header(None, description="Bearer access token"),
    token: Optional[str] = Query(None, description="Token query parameter for SSE/EventSource"),
    identity_provider: IIdentityProvider = Depends(get_identity_provider),
) -> UserIdentity:
    """Authenticate using Authorization header, with query token fallback for SSE/EventSource."""
    raw_token = None
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            raw_token = credentials.strip()
    elif token and token.strip():
        raw_token = token.strip()
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Bearer authorization token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = identity_provider.verify_access_token(raw_token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or revoked access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_permission(permission: Permission | str) -> Callable[[UserIdentity], UserIdentity]:
    def _dependency(user: UserIdentity = Depends(get_current_user)) -> UserIdentity:
        perm_str = permission.value if hasattr(permission, "value") else str(permission)
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Requires '{perm_str}' permission.",
            )
        return user
    return _dependency


def verify_farm_access(user: UserIdentity, target_farm_id: str) -> None:
    if not user.can_access_farm(target_farm_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-farm access forbidden.",
        )
