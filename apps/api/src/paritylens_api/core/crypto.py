"""Encrypting the secrets users store (API keys for the APIs under test).

AES-256-GCM: the ciphertext cannot be read without the key, and cannot be
altered without detection. Each value gets a fresh random nonce, and the
row it belongs to is bound in as associated data, so a ciphertext copied
onto another row fails to decrypt.

The key is one master key from the environment. `key_version` is stored
with each ciphertext so that rows written under different keys can be
told apart. Rotating the key (holding two keys and re-encrypting) is not
implemented yet; a value from another version is refused, by name.
"""

import base64
import os
import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_BYTES = 12
_KEY_BYTES = 32


def secret_context(project_id: uuid.UUID, name: str) -> str:
    """What a stored secret's ciphertext is bound to.

    Copied to another project or renamed, the ciphertext will not decrypt.
    """
    return f"secret:{project_id}:{name}"


class DecryptionError(Exception):
    """The ciphertext was not produced with this key for this context."""


@dataclass(frozen=True)
class Encrypted:
    ciphertext: bytes
    nonce: bytes
    key_version: int


class SecretBox:
    def __init__(self, master_key_base64: str, key_version: int) -> None:
        key = base64.b64decode(master_key_base64, validate=True)
        if len(key) != _KEY_BYTES:
            raise ValueError(f"the master key must be {_KEY_BYTES} bytes, base64-encoded")
        self._aead = AESGCM(key)
        self._key_version = key_version

    def encrypt(self, plaintext: str, *, context: str) -> Encrypted:
        """Encrypt a value. `context` says what it belongs to, e.g. a row's identity."""
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aead.encrypt(nonce, plaintext.encode("utf-8"), context.encode("utf-8"))
        return Encrypted(ciphertext=ciphertext, nonce=nonce, key_version=self._key_version)

    def decrypt(self, encrypted: Encrypted, *, context: str) -> str:
        if encrypted.key_version != self._key_version:
            raise DecryptionError(f"no key for version {encrypted.key_version}")
        try:
            plaintext = self._aead.decrypt(
                encrypted.nonce, encrypted.ciphertext, context.encode("utf-8")
            )
        except InvalidTag as exc:
            raise DecryptionError("the value could not be decrypted") from exc
        return plaintext.decode("utf-8")
