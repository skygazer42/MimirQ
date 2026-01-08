"""
Security helpers for password hashing and verification.
"""
import bcrypt


def hash_password(password: str) -> str:
    """Hash a plaintext password."""
    password_bytes = (password or "").encode("utf-8")
    if len(password_bytes) > 72:
        raise ValueError("Password cannot be longer than 72 bytes for bcrypt")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a hash."""
    try:
        return bcrypt.checkpw(
            (plain_password or "").encode("utf-8"),
            (hashed_password or "").encode("utf-8"),
        )
    except Exception:
        return False
