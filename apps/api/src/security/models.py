"""Security, identity, and RBAC models for Aqua OS."""

from enum import Enum
from typing import List

from pydantic import BaseModel, ConfigDict, Field


class Role(str, Enum):
    """User and service roles with increasing privileges."""

    VIEWER = "viewer"
    OPERATOR = "operator"
    FARM_MANAGER = "farm_manager"
    SYSTEM_ADMIN = "system_admin"


class Permission(str, Enum):
    """Granular system permissions."""

    PONDS_READ = "ponds:read"
    PONDS_WRITE = "ponds:write"
    TELEMETRY_READ = "telemetry:read"
    TELEMETRY_WRITE = "telemetry:write"
    ADVISORY_ACK = "advisory:ack"
    AUDIT_READ = "audit:read"
    USERS_MANAGE = "users:manage"
    EQUIPMENT_ACTUATE = "equipment:actuate"


ROLE_PERMISSIONS = {
    Role.VIEWER: [
        Permission.PONDS_READ,
        Permission.TELEMETRY_READ,
    ],
    Role.OPERATOR: [
        Permission.PONDS_READ,
        Permission.TELEMETRY_READ,
        Permission.TELEMETRY_WRITE,
        Permission.ADVISORY_ACK,
    ],
    Role.FARM_MANAGER: [
        Permission.PONDS_READ,
        Permission.PONDS_WRITE,
        Permission.TELEMETRY_READ,
        Permission.TELEMETRY_WRITE,
        Permission.ADVISORY_ACK,
        Permission.AUDIT_READ,
    ],
    Role.SYSTEM_ADMIN: [p for p in Permission],
}


class UserIdentity(BaseModel):
    """Authenticated user context attached to request."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    username: str
    farm_id: str
    role: Role
    permissions: List[Permission]
    is_active: bool = True

    def has_permission(self, permission: Permission | str) -> bool:
        if self.role == Role.SYSTEM_ADMIN:
            return True
        return permission in self.permissions or permission in [p.value for p in self.permissions]

    def can_access_farm(self, farm_id: str) -> bool:
        if self.role == Role.SYSTEM_ADMIN:
            return True
        return self.farm_id == farm_id


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    user_id: str
    username: str
    farm_id: str
    role: Role


class TokenPayload(BaseModel):
    sub: str  # user_id
    username: str
    farm_id: str
    role: str
    permissions: List[str]
    exp: int
    iat: int
    jti: str  # unique token ID for revocation

