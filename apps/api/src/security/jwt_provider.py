"""JWT-based implementation of IIdentityProvider."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.infrastructure.models import RevokedTokenORM, UserORM
from apps.api.src.security.interfaces import IIdentityProvider
from apps.api.src.security.models import (
    ROLE_PERMISSIONS,
    Role,
    TokenResponse,
    UserIdentity,
)
from apps.api.src.security.password import verify_password

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15


class LocalJWTIdentityProvider(IIdentityProvider):
    """Local JWT authentication provider with lockout and revocation support."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._secret = settings.jwt_secret_key
        self._algorithm = "HS256"

    def authenticate_user(self, username: str, password: str) -> Optional[UserIdentity]:
        user_record = (
            self._session.query(UserORM)
            .filter(UserORM.username == username)
            .first()
        )
        if not user_record or not user_record.is_active:
            return None

        # Check account lockout
        now = datetime.now(timezone.utc)
        if user_record.locked_until:
            locked_dt = user_record.locked_until
            if locked_dt.tzinfo is None:
                locked_dt = locked_dt.replace(tzinfo=timezone.utc)
            if now < locked_dt:
                return None  # Account temporarily locked

        # Verify password
        if not verify_password(password, user_record.password_hash):
            user_record.failed_login_attempts += 1
            if user_record.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                user_record.locked_until = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            self._session.commit()
            return None

        # Reset failed attempts on success
        user_record.failed_login_attempts = 0
        user_record.locked_until = None
        self._session.commit()

        role = Role(user_record.role)
        permissions = ROLE_PERMISSIONS.get(role, [])

        return UserIdentity(
            user_id=user_record.user_id,
            username=user_record.username,
            farm_id=user_record.farm_id,
            role=role,
            permissions=permissions,
            is_active=user_record.is_active,
        )

    def create_access_token(
        self,
        user: UserIdentity,
        expires_delta: Optional[timedelta] = None,
    ) -> TokenResponse:
        now = datetime.now(timezone.utc)
        delta = expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)
        expires_at = now + delta
        jti = str(uuid.uuid4())

        payload = {
            "sub": user.user_id,
            "username": user.username,
            "farm_id": user.farm_id,
            "role": user.role.value,
            "permissions": [p.value for p in user.permissions],
            "exp": int(expires_at.timestamp()),
            "iat": int(now.timestamp()),
            "jti": jti,
        }

        token = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in_seconds=int(delta.total_seconds()),
            user_id=user.user_id,
            username=user.username,
            farm_id=user.farm_id,
            role=user.role,
        )

    def verify_access_token(self, token: str) -> Optional[UserIdentity]:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"require": ["exp", "sub", "jti"]},
            )
            jti = payload.get("jti")
            if not jti:
                return None

            # Check revocation blacklist
            revoked = (
                self._session.query(RevokedTokenORM)
                .filter(RevokedTokenORM.jti == jti)
                .first()
            )
            if revoked:
                return None

            # Verify active user in database
            user_id = payload.get("sub")
            user_record = (
                self._session.query(UserORM)
                .filter(UserORM.user_id == user_id, UserORM.is_active.is_(True))
                .first()
            )
            if not user_record:
                return None

            role = Role(payload["role"])
            permissions = ROLE_PERMISSIONS.get(role, [])

            return UserIdentity(
                user_id=user_record.user_id,
                username=user_record.username,
                farm_id=user_record.farm_id,
                role=role,
                permissions=permissions,
                is_active=user_record.is_active,
            )
        except Exception:
            return None

    def revoke_token(self, token: str) -> bool:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"verify_exp": False},
            )
            jti = payload.get("jti")
            exp_ts = payload.get("exp")
            if not jti or not exp_ts:
                return False

            exp_dt = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
            revoked = RevokedTokenORM(jti=jti, expires_at=exp_dt)
            self._session.add(revoked)
            self._session.commit()
            return True
        except Exception:
            return False

