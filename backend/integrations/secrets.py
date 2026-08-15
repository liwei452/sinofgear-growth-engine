import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings


def _encryption_key() -> bytes:
    return hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()


def encrypt_secret(plaintext: str) -> str:
    if not plaintext:
        raise ValueError("Cannot encrypt an empty secret.")
    nonce = os.urandom(12)
    ciphertext = AESGCM(_encryption_key()).encrypt(
        nonce, plaintext.encode("utf-8"), None,
    )
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(token: str) -> str:
    if not token:
        raise ValueError("Cannot decrypt an empty secret.")
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        nonce, ciphertext = raw[:12], raw[12:]
        return AESGCM(_encryption_key()).decrypt(nonce, ciphertext, None).decode("utf-8")
    except Exception as error:
        raise ValueError("Unable to decrypt the stored secret.") from error
