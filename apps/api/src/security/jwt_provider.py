"""JWT identity provider with lockout and revocation support."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.infrastructure.models import RevokedTokenORM, UserORM
from apps.api.src.security.interfaces import IIdentityProvider
from apps.api.src.security.models import ROLE_PERMISSIONS, Role, TokenResponse, UserIdentity
from apps.api.src.security.password import verify_password

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15


class LocalJWTIdentityProvider(IIdentityProvider):
    """Local JWT implementation; all token validation is fail-closed."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._secret = settings.jwt_secret_key
        self._algorithm = "HS256"

    def authenticate_user(self, username: str, password: str) -> Optional[UserIdentity]:
        record = self._session.query(UserORM).filter(UserORM.username == username).first()
        if not record or not record.is_active:
            return None
        now = datetime.now(timezone.utc)
        if record.locked_until:
            locked_until = record.locked_until
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            if now < locked_until:
                return None
        if not verify_password(password, record.password_hash):
            record.failed_login_attempts += 1
            if record.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                record.locked_until = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            self._session.commit()
            return None
        record.failed_login_attempts = 0
        record.locked_until = None
        self._session.commit()
        role = Role(record.role)
        return UserIdentity(
            user_id=record.user_id, username=record.username, farm_id=record.farm_id,
            role=role, permissions=ROLE_PERMISSIONS.get(role, []), is_active=record.is_active,
        )

    def create_access_token(self, user: UserIdentity, expires_delta: Optional[timedelta] = None) -> TokenResponse:
        now = datetime.now(timezone.utc)
        delta = expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)
        expires_at = now + delta
        payload = {
            "iss": "aqua-os", "aud": "aqua-os-api",
            "sub": user.user_id, "username": user.username, "farm_id": user.farm_id,
            "role": user.role.value, "permissions": [p.value for p in user.permissions],
            "exp": int(expires_at.timestamp()), "iat": int(now.timestamp()), "jti": str(uuid.uuid4()),
        }
        token = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        return TokenResponse(
            access_token=token, token_type="bearer", expires_in_seconds=int(delta.total_seconds()),
            user_id=user.user_id, username=user.username, farm_id=user.farm_id, role=user.role,
        )

    def verify_access_token(self, token: str) -> Optional[UserIdentity]:
        try:
            payload = jwt.decode(
                token, self._secret, algorithms=[self._algorithm],
                issuer="aqua-os", audience="aqua-os-api",
                options={"require": ["exp", "iat", "sub", "jti", "iss", "aud"]},
            )
            jti, user_id = payload.get("jti"), payload.get("sub")
            if not isinstance(jti, str) or not isinstance(user_id, str):
                return None
            if self._session.query(RevokedTokenORM).filter(RevokedTokenORM.jti == jti).first():
                return None
            record = self._session.query(UserORM).filter(
                UserORM.user_id == user_id, UserORM.is_active.is_(True)
            ).first()
            if not record:
                return None
            # Identity and tenant claims are taken from the database, not trusted from JWT.
            role = Role(record.role)
            return UserIdentity(
                user_id=record.user_id, username=record.username, farm_id=record.farm_id,
                role=role, permissions=ROLE_PERMISSIONS.get(role, []), is_active=record.is_active,
            )
        except (jwt.PyJWTError, KeyError, TypeError, ValueError):
            return None

    def revoke_token(self, token: str) -> bool:
        try:
            payload = jwt.decode(
                token, self._secret, algorithms=[self._algorithm],
                issuer="aqua-os", audience="aqua-os-api",
                options={"verify_exp": False, "require": ["sub", "jti", "exp", "iss", "aud"]},
            )
            jti, exp_ts = payload.get("jti"), payload.get("exp")
            if not isinstance(jti, str) or not isinstance(exp_ts, (int, float)):
                return False
            existing = self._session.query(RevokedTokenORM).filter(RevokedTokenORM.jti == jti).first()
            if existing:
                return True
            self._session.add(RevokedTokenORM(
                jti=jti, expires_at=datetime.fromtimestamp(exp_ts, tz=timezone.utc)
            ))
            self._session.commit()
            return True
        except (jwt.PyJWTError, KeyError, TypeError, ValueError):
            self._session.rollback()
            return False
