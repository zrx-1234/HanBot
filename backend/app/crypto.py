"""敏感字段落库加密（design §15.4）。

AES-256-GCM，密钥由 HANBOT_DATA_KEY 经 scrypt 派生；每次加密随机 nonce，
密文格式 base64(nonce(12B) + ciphertext+tag)。GCM 自带完整性校验，
篡改或换密钥解密直接失败，不会静默出错。
"""

import base64
import binascii
import hashlib
import os
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_SALT = b"hanbot.aes.v1"
_ASSOC_DATA = b"hanbot.credential"


@lru_cache(maxsize=8)
def _derive_key(secret: str) -> bytes:
    return hashlib.scrypt(secret.encode(), salt=_SALT, n=2**14, r=8, p=1, dklen=32)


def encrypt_value(secret: str, plaintext: str) -> str:
    key = _derive_key(secret)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode(), _ASSOC_DATA)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_value(secret: str, blob: str) -> str:
    key = _derive_key(secret)
    try:
        raw = base64.b64decode(blob, validate=True)
        nonce, ciphertext = raw[:12], raw[12:]
        return AESGCM(key).decrypt(nonce, ciphertext, _ASSOC_DATA).decode()
    except (InvalidTag, binascii.Error, ValueError, UnicodeDecodeError) as e:
        raise ValueError("解密失败：HANBOT_DATA_KEY 与加密时不一致，或数据损坏") from e
