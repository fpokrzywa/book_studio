"""Password hashing with scrypt (Python standard library; no extra dependency).

Format: ``scrypt$<log2 n>$<r>$<p>$<salt b64>$<hash b64>``. Parameters are stored with each hash
so they can be raised later without breaking existing accounts. n=2**17, r=8, p=1 (128 MiB per
hash) is the first scrypt setting in the OWASP Password Storage Cheat Sheet (read 2026-11-23).
Tests lower LOG2_N for speed; verification always uses the parameters stored in the hash.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

LOG2_N = 17
R = 8
P = 1
DKLEN = 32
MIN_LENGTH = 12
MAX_LENGTH = 1024  # bounds the hashing cost of a hostile request


class PasswordPolicyError(ValueError):
    pass


def check_policy(password: str, username: str = "") -> None:
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"Use at most {MAX_LENGTH} characters.")
    if username and password.strip().lower() == username.strip().lower():
        raise PasswordPolicyError("The password must not be the same as the username.")


def _derive(password: str, salt: bytes, log2_n: int, r: int, p: int) -> bytes:
    n = 1 << log2_n
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=DKLEN, maxmem=256 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt, LOG2_N, R, P)
    b64 = base64.b64encode
    return f"scrypt${LOG2_N}${R}${P}${b64(salt).decode()}${b64(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    if len(password) > MAX_LENGTH:
        return False
    try:
        algo, log2_n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        got = _derive(password, base64.b64decode(salt_b64), int(log2_n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


# A real hash of a random password: verifying against it costs the same as a real account, so a
# failed sign-in for an unknown username takes as long as one for a known username.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
