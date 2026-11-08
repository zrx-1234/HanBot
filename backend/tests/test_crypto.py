import pytest

from app.crypto import decrypt_value, encrypt_value

_SECRET = "test-data-key-0123456789abcdef0123"


def test_roundtrip():
    blob = encrypt_value(_SECRET, "sk-abc-12345678")
    assert "sk-abc-12345678" not in blob
    assert decrypt_value(_SECRET, blob) == "sk-abc-12345678"


def test_random_nonce_yields_different_ciphertexts():
    a = encrypt_value(_SECRET, "same-plaintext")
    b = encrypt_value(_SECRET, "same-plaintext")
    assert a != b
    # 两次都能解回原文（随机 nonce 不影响解密）
    assert decrypt_value(_SECRET, a) == "same-plaintext"
    assert decrypt_value(_SECRET, b) == "same-plaintext"


def test_wrong_key_rejected():
    blob = encrypt_value(_SECRET, "secret-value")
    with pytest.raises(ValueError):
        decrypt_value("another-key-0123456789abcdef012345", blob)


def test_tampered_ciphertext_rejected():
    blob = encrypt_value(_SECRET, "secret-value")
    tampered = blob[:-3] + "AAA"
    with pytest.raises(ValueError):
        decrypt_value(_SECRET, tampered)


def test_corrupted_blob_rejected():
    with pytest.raises(ValueError):
        decrypt_value(_SECRET, "not-base64-!!!")
