"""Password hashing and verification for Aqua OS.

PBKDF2-HMAC-SHA256 with per-password random salts. The iteration count is
configurable in the stored format so hashes can be upgraded over time.
"""
import hashlib
import secrets

DEFAULT_ITERATIONS = 600_000
HASH_NAME = "sha256"
SALT_BYTES = 16
DERIVED_KEY_BYTES = 32
_ALGORITHM = "pbkdf2_sha256"


def hash_password(password: str, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Return a self-describing salted password hash; never store plaintext."""
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a non-empty string")
    if iterations < 100_000:
        raise ValueError("Password hashing iterations are below the supported minimum")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        HASH_NAME, password.encode("utf-8"), salt, iterations,
        dklen=DERIVED_KEY_BYTES,
    )
    return f"{_ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(plain_password: str, stored_hash: str) -> bool:
    """Constant-time verification; rejects malformed or unreasonable hash records."""
    try:
        algorithm, iterations_text, salt_text, digest_text = stored_hash.split("$")
        if algorithm != _ALGORITHM:
            return False
        iterations = int(iterations_text)
        # Bounds prevent corrupt database values from causing unbounded CPU work.
        if not 100_000 <= iterations <= 2_000_000:
            return False
        salt = bytes.fromhex(salt_text)
        expected = bytes.fromhex(digest_text)
        if len(salt) != SALT_BYTES or len(expected) != DERIVED_KEY_BYTES:
            return False
        actual = hashlib.pbkdf2_hmac(
            HASH_NAME, plain_password.encode("utf-8"), salt, iterations,
            dklen=DERIVED_KEY_BYTES,
        )
        return secrets.compare_digest(actual, expected)
    except (AttributeError, TypeError, ValueError):
        return False
