"""Secure password hashing and verification using PBKDF2-HMAC-SHA256."""

import hashlib
import secrets

ITERATIONS = 100_000
HASH_NAME = "sha256"
SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Hash password with a unique salt using OWASP-recommended PBKDF2-HMAC-SHA256."""
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        hash_name=HASH_NAME,
        password=password.encode("utf-8"),
        salt=salt,
        iterations=ITERATIONS,
    )
    salt_hex = salt.hex()
    hash_hex = derived.hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt_hex}${hash_hex}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against stored hash using constant-time comparison."""
    try:
        parts = hashed_password.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected_hash = parts[3]

        derived = hashlib.pbkdf2_hmac(
            hash_name=HASH_NAME,
            password=plain_password.encode("utf-8"),
            salt=salt,
            iterations=iterations,
        )
        return secrets.compare_digest(derived.hex(), expected_hash)
    except Exception:
        return False

