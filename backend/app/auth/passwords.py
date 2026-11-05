from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(password_hash: str, plain: str) -> bool:
    try:
        return _hasher.verify(password_hash, plain)
    except (VerificationError, InvalidHashError):
        # 不匹配、哈希损坏（如手工改库改坏）一律按验证失败处理，不冒500
        return False
