from __future__ import annotations

import hashlib
import logging
import shutil
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

from janus_biometrics.errors import BiometricsError

logger = logging.getLogger(__name__)

DEFAULT_MODEL_IDLE_UNLOAD_S = 300
_CHUNK_SIZE = 1 << 20  # 1 MiB


class ModelIntegrityError(BiometricsError):
    """Raised when a downloaded or local model file fails hash verification."""

    def __init__(self, model_id: str, expected_sha256: str, actual_sha256: str) -> None:
        super().__init__(
            f"Model '{model_id}' failed integrity check: "
            f"expected sha256={expected_sha256}, got sha256={actual_sha256}. "
            "Refusing to load a model whose weights do not match the configured hash."
        )
        self.model_id = model_id
        self.expected_sha256 = expected_sha256
        self.actual_sha256 = actual_sha256


class ModelSourceError(BiometricsError):
    """Raised when a model cannot be obtained from its configured source."""


class ModelConfigError(BiometricsError):
    """Raised when models.yaml is missing, malformed, or missing an entry."""


@dataclass(frozen=True)
class ModelSpec:
    """One entry from models.yaml.

    Exactly one of `url` or `local_path` must be set. `sha256` is required
    in both cases: for `url` it is verified after download, for
    `local_path` it is verified before every load, since a local file can
    change on disk between runs without janus_biometrics knowing.
    """

    model_id: str
    sha256: str
    url: str | None = None
    local_path: str | None = None
    license: str | None = None

    def __post_init__(self) -> None:
        if bool(self.url) == bool(self.local_path):
            raise ModelConfigError(
                f"Model '{self.model_id}' must set exactly one of 'url' or 'local_path'"
            )
        if not self.sha256:
            raise ModelConfigError(f"Model '{self.model_id}' is missing a required 'sha256'")


def load_model_specs(config_path: Path) -> dict[str, ModelSpec]:
    """Parses models.yaml into a dict keyed by model_id.

    Expected shape:

        models:
          yunet:
            sha256: "TODO(confirm): sha256 of face_detection_yunet_2023mar.onnx"
            url: "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
            license: "MIT"
          sface:
            sha256: "TODO(confirm): sha256 of face_recognition_sface_2021dec.onnx"
            url: "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
            license: "Apache-2.0"
          minifasnet:
            sha256: "TODO(confirm): sha256 of the combined MiniFASNetV2+V1SE weights"
            local_path: "/opt/janus/models/minifasnet_v2_v1se.onnx"
            license: "TODO(confirm): see spec-18 Open Questions before redistributing"

    A `local_path` entry lets an operator supply weights themselves (no
    network access required, no license-redistribution question), which is
    why both source kinds are supported rather than only URLs.
    """
    if not config_path.exists():
        raise ModelConfigError(f"Model config not found at {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ModelConfigError(f"Could not parse {config_path}: {exc}") from exc

    entries = raw.get("models", {})
    if not entries:
        raise ModelConfigError(f"{config_path} has no 'models' section")

    specs: dict[str, ModelSpec] = {}
    for model_id, entry in entries.items():
        specs[model_id] = ModelSpec(
            model_id=model_id,
            sha256=entry.get("sha256", ""),
            url=entry.get("url"),
            local_path=entry.get("local_path"),
            license=entry.get("license"),
        )
    return specs


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url) as response, tmp_dest.open("wb") as out_file:  # noqa: S310
            shutil.copyfileobj(response, out_file, length=_CHUNK_SIZE)
    except (OSError, ValueError) as exc:
        tmp_dest.unlink(missing_ok=True)
        raise ModelSourceError(f"Could not download model from '{url}': {exc}") from exc
    tmp_dest.replace(dest)


@dataclass
class _CacheEntry:
    path: Path
    last_used: float


class ModelCache:
    """Resolves ModelSpecs to verified local file paths, with lazy loading
    and idle-based cleanup of the download cache (requisito: models.py
    step in the biometrics handoff).

    This class only resolves and verifies *files*. It does not load ONNX
    sessions; that is the caller's responsibility (providers/sface.py),
    so this stays reusable for any future ONNX-backed provider.
    """

    def __init__(
        self,
        config_path: Path,
        cache_dir: Path,
        model_idle_unload_s: float = DEFAULT_MODEL_IDLE_UNLOAD_S,
        clock: callable = time.monotonic,
    ) -> None:
        self._specs = load_model_specs(config_path)
        self._cache_dir = cache_dir
        self._model_idle_unload_s = model_idle_unload_s
        self._clock = clock
        self._entries: dict[str, _CacheEntry] = {}

    def resolve(self, model_id: str) -> Path:
        """Returns a verified local path for model_id, downloading it first
        if it is a URL-sourced model not yet cached. Always re-verifies the
        hash for local_path models, since those can change on disk outside
        of janus_biometrics's control."""
        spec = self._specs.get(model_id)
        if spec is None:
            raise ModelConfigError(f"No model config entry for '{model_id}'")

        path = self._resolve_path(spec)
        actual = _sha256_of(path)
        if actual != spec.sha256:
            raise ModelIntegrityError(model_id, spec.sha256, actual)

        self._entries[model_id] = _CacheEntry(path=path, last_used=self._clock())
        self._evict_idle()
        return path

    def _resolve_path(self, spec: ModelSpec) -> Path:
        if spec.local_path is not None:
            local = Path(spec.local_path)
            if not local.exists():
                raise ModelSourceError(f"local_path for '{spec.model_id}' does not exist: {local}")
            return local

        cached = self._cache_dir / f"{spec.model_id}.onnx"
        if cached.exists():
            return cached
        logger.info("downloading model '%s' from %s", spec.model_id, spec.url)
        _download(spec.url, cached)  # type: ignore[arg-type]
        return cached

    def _evict_idle(self) -> None:
        now = self._clock()
        for model_id, entry in list(self._entries.items()):
            if now - entry.last_used <= self._model_idle_unload_s:
                continue
            spec = self._specs.get(model_id)
            if spec is not None and spec.local_path is not None:
                # Never delete operator-supplied files, only our own cache.
                continue
            logger.info(
                "evicting idle model '%s' (path kept on disk, session unloaded by caller)",
                model_id,
            )
            del self._entries[model_id]

    def is_loaded(self, model_id: str) -> bool:
        return model_id in self._entries

    def license_for(self, model_id: str) -> str | None:
        spec = self._specs.get(model_id)
        return spec.license if spec else None
