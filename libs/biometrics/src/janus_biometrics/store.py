from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from janus_biometrics.base import Enrollment
from janus_biometrics.errors import KeyUnavailable

_NONCE_SIZE = 12


class EncryptedTemplateStore:
    """AES-256-GCM authenticated storage for enrolled templates
    (requisitos 15 and 17). Never stores raw samples, only embeddings and
    the centroid. Lives under state_dir/biometrics/<kind>/<profile>.enc,
    never in janus.db."""

    def __init__(self, state_dir: Path, key: bytes) -> None:
        if len(key) != 32:
            raise KeyUnavailable("Template encryption key must be 32 bytes (AES-256)")
        self._root = Path(state_dir) / "biometrics"
        self._aesgcm = AESGCM(key)

    def save(self, enrollment: Enrollment) -> None:
        path = self._path_for(enrollment.kind, enrollment.profile)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(enrollment), default=str).encode("utf-8")
        nonce = secrets.token_bytes(_NONCE_SIZE)
        ciphertext = self._aesgcm.encrypt(nonce, payload, associated_data=None)
        path.write_bytes(nonce + ciphertext)

    def load(self, kind: str, profile: str) -> Enrollment | None:
        path = self._path_for(kind, profile)
        if not path.exists():
            return None
        raw = path.read_bytes()
        nonce, ciphertext = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
        try:
            payload = self._aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        except InvalidTag as exc:
            raise KeyUnavailable(
                f"Template for {kind}/{profile} could not be decrypted: "
                "wrong key or the file has been tampered with."
            ) from exc
        data = json.loads(payload)
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        return Enrollment(**data)

    def delete(self, kind: str, profile: str) -> None:
        """Securely deletes a template: overwrites before unlinking."""
        path = self._path_for(kind, profile)
        if not path.exists():
            return
        size = path.stat().st_size
        with path.open("r+b") as handle:
            handle.write(secrets.token_bytes(size))
            handle.flush()
            os.fsync(handle.fileno())
        path.unlink()

    def exists(self, kind: str, profile: str) -> bool:
        return self._path_for(kind, profile).exists()

    def _path_for(self, kind: str, profile: str) -> Path:
        return self._root / kind / f"{profile}.enc"
