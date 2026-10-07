import hashlib


def sha256_hex(value: str) -> str:
    """Hash for high-entropy random secrets (refresh tokens, API keys): fast is fine here."""
    return hashlib.sha256(value.encode()).hexdigest()
