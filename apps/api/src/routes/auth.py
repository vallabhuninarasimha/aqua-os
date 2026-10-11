"""Authentication routes for Aqua OS."""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from apps.api.src.dependencies import get_db_session
from apps.api.src.security.audit import log_security_event
from apps.api.src.security.dependencies import (
    get_current_user,
    get_identity_provider,
)
from apps.api.src.security.interfaces import IIdentityProvider
from apps.api.src.security.models import (
    LoginRequest,
    TokenResponse,
    UserIdentity,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    credentials: LoginRequest,
    session: Session = Depends(get_db_session),
    idp: IIdentityProvider = Depends(get_identity_provider),
) -> TokenResponse:
    """Authenticate with username and password, returning a signed JWT access token."""
    user = idp.authenticate_user(credentials.username, credentials.password)
    client_ip = request.client.host if request.client else None

    if not user:
        # Audit failed login attempt
        log_security_event(
            session=session,
            farm_id="system",
            user_id=credentials.username,
            action="LOGIN_FAILED",
            resource_type="auth",
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or account temporarily locked.",
        )

    token_resp = idp.create_access_token(user)

    # Audit successful login
    log_security_event(
        session=session,
        farm_id=user.farm_id,
        user_id=user.user_id,
        action="LOGIN_SUCCESS",
        resource_type="auth",
        ip_address=client_ip,
    )
    return token_resp


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    authorization: Optional[str] = Header(None),
    current_user: UserIdentity = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    idp: IIdentityProvider = Depends(get_identity_provider),
) -> dict:
    """Revoke current access token."""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        idp.revoke_token(token)

    log_security_event(
        session=session,
        farm_id=current_user.farm_id,
        user_id=current_user.user_id,
        action="LOGOUT",
        resource_type="auth",
    )
    return {"message": "Token successfully revoked."}


@router.get("/me", response_model=UserIdentity)
async def get_current_user_profile(
    current_user: UserIdentity = Depends(get_current_user),
) -> UserIdentity:
    """Retrieve identity, role, and permissions of the currently authenticated user."""
    return current_user

