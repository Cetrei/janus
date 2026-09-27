from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, SecretStr, model_validator


class ConfigError(Exception):
    """Raised on invalid configuration. NOTE: spec-02 (requisito 3) wants this
    to carry a full list of field-level errors with masked secrets; that
    richer shape is not implemented yet. This is a plain exception for now,
    used only by SecretRef.resolve()."""


class SecretRef(BaseModel):
    """A secret referenced by source, never inlined as plaintext by default
    (spec-02, requisito 4). Accepts exactly one of `env` (environment
    variable name) or `file` (path to a file whose contents are the secret).

    `repr()` never shows the resolved value, only which source is
    configured, so an accidental log/print does not leak the secret.
    """

    env: str | None = None
    file: str | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "SecretRef":
        if bool(self.env) == bool(self.file):
            raise ValueError("SecretRef must set exactly one of 'env' or 'file'")
        return self

    def resolve(self) -> SecretStr:
        if self.env is not None:
            import os

            value = os.environ.get(self.env)
            if value is None:
                raise ConfigError(f"Environment variable '{self.env}' is not set")
            return SecretStr(value)

        path = Path(self.file)  # type: ignore[arg-type]
        if not path.exists():
            raise ConfigError(f"Secret file not found: {path}")
        return SecretStr(path.read_text(encoding="utf-8").strip())

    def __repr__(self) -> str:
        source = f"env={self.env!r}" if self.env else f"file={self.file!r}"
        return f"SecretRef({source})"
