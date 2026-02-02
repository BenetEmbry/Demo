from __future__ import annotations

from cryptography.fernet import Fernet

from regression.at_rest_encryption import decrypt_bytes, encrypt_bytes


def test_at_rest_encryption_roundtrip(monkeypatch) -> None:  # noqa: ANN001
    key = Fernet.generate_key()
    monkeypatch.setenv("ARTIFACT_ENCRYPTION_KEY", key.decode("utf-8"))

    plaintext = b"{\"hello\":\"world\",\"secret\":\"do-not-store-in-plain\"}"
    ciphertext = encrypt_bytes(plaintext)

    assert ciphertext != plaintext
    assert b"do-not-store-in-plain" not in ciphertext

    recovered = decrypt_bytes(ciphertext)
    assert recovered == plaintext
