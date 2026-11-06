from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# argon2id parameters from AUTH_RBAC_PLAN §1.1
hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
MAX_LENGTH = 128
_DUMMY_HASH: str | None = None


@lru_cache
def _common_passwords() -> frozenset[str]:
    path = Path(__file__).with_name("common_passwords.txt")
    return frozenset(line.strip().lower() for line in path.read_text().splitlines() if line.strip())


def hash_password(password: str) -> str:
    return hasher.hash(password)


# Returns (ok, needs_rehash)
def verify_password(password_hash: str, password: str) -> tuple[bool, bool]:
    try:
        hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False, False
    return True, hasher.check_needs_rehash(password_hash)


# Same work as a real verify, so unknown emails take as long as wrong passwords
def dummy_verify(password: str) -> None:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hasher.hash("dummy-password-for-timing")
    verify_password(_DUMMY_HASH, password)


# NIST 800-63B style policy: length only, no composition rules; reject common and email-based
def password_problems(password: str, email: str, min_length: int) -> list[str]:
    problems = []
    if len(password) < min_length:
        problems.append(f"Password must be at least {min_length} characters")
    if len(password) > MAX_LENGTH:
        problems.append(f"Password must be at most {MAX_LENGTH} characters")
    lowered = password.lower()
    if lowered in _common_passwords():
        problems.append("Password is too common")
    local_part = email.split("@")[0].lower()
    if lowered in {email.lower(), local_part} or (len(local_part) >= 4 and local_part in lowered):
        problems.append("Password must not contain your email or username")
    return problems
