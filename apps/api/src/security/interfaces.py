"""Authentication and Identity Provider interfaces."""

from datetime import timedelta
from typing import Optional, Protocol

from apps.api.src.security.models import TokenResponse, UserIdentity


class IIdentityProvider(Protocol):
    """Abstract identity and token provider.

    Decouples authentication mechanism from routes, allowing local JWT,
    Keycloak, Auth0, or OAuth2/OIDC substitution without breaking changes.
    """

    def authenticate_user(self, username: str, password: str) -> Optional[UserIdentity]:
        """Verify credentials and return user identity if valid."""
        ...

    def create_access_token(
        self,
        user: UserIdentity,
        expires_delta: Optional[timedelta] = None,
    ) -> TokenResponse:
        """Issue signed access token with user claims and permissions."""
        ...

    def verify_access_token(self, token: str) -> Optional[UserIdentity]:
        """Validate token signature, expiration, and revocation status."""
        ...

    def revoke_token(self, token: str) -> bool:
        """Revoke a token before its natural expiry."""
        ...

