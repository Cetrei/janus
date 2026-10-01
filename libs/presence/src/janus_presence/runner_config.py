"""Declarative configuration of the autonomous runner (SPEC.md ampliación,
requisito 39).

The file is TOML validated by Pydantic, the choice the rest of Janus already
made (docs/stack/06-config-toml-pydantic.md): TOML does not silently
reinterpret values the way YAML does, and unknown keys are rejected so a
typo in a threshold fails at startup instead of being ignored.

Two things are deliberately absent:

* Defaults for the match thresholds (requisito 5). They must come from
  calibrating with real data, so the file has to state them.
* Any `mcp` source. Those need a tool injected by Janus (requisito 10),
  which a standalone runner does not have.

Example:

    state_dir = "~/.local/share/janus"

    [presence]
    match_threshold = 0.6
    match_threshold_ambiguous = 1.2

    [[sources]]
    source_id = "cuarto"
    kind = "camera"
    device = 3
    sample_fps = 4

    [[sources]]
    source_id = "mic-cuarto"
    kind = "microphone"
    device = "default"

    [wakeword]
    host = "127.0.0.1"
    port = 10400
    names = ["ok_nabu"]

    [home_assistant]
    url = "http://127.0.0.1:8123"
    token_file = "~/.config/janus/ha.token"
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from janus_presence.errors import PresenceError
from janus_presence.ha_sink import DEFAULT_QUEUE_SIZE, DEFAULT_TIMEOUT_S
from janus_presence.models import PresenceConfig, SourceConfig, SourceKind, SourceLocation

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_SOURCE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
_MAX_PORT = 65_535
_DEFAULT_REVIEW_PORT = 8765
_DEFAULT_EVENT_LOG_MAX_BYTES = 10 * 1024 * 1024
_HA_SCHEMES = ("http://", "https://")


class RunnerConfigError(PresenceError):
    """The runner config file is unreadable, malformed or inconsistent."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _expanded(value: Path | None) -> Path | None:
    return value.expanduser() if value is not None else None


class PresenceSection(_Section):
    """The knobs of PresenceConfig. Only the two match thresholds are
    mandatory; everything else keeps PresenceConfig's own default unless the
    file overrides it."""

    match_threshold: float = Field(gt=0)
    match_threshold_ambiguous: float = Field(gt=0)
    voice_match_threshold: float | None = Field(default=None, gt=0)
    voice_match_threshold_ambiguous: float | None = Field(default=None, gt=0)
    clip_duration_s: int | None = Field(default=None, gt=0)
    clip_preroll_s: int | None = Field(default=None, ge=0)
    clips_max_total_mb: int | None = Field(default=None, gt=0)
    unknown_snapshot_retention_s: int | None = Field(default=None, gt=0)
    roles: list[str] | None = None
    established_min_samples: int | None = Field(default=None, gt=0)
    provisional_confidence_cap: float | None = Field(default=None, gt=0, le=1)
    auto_reinforce_dual_modality: bool | None = None
    max_samples_per_person: int | None = Field(default=None, gt=0)
    visit_gap_s: int | None = Field(default=None, gt=0)
    forget_after_days: int | None = Field(default=None, gt=0)

    def overrides(self) -> dict[str, object]:
        """Only what the file set, so unset knobs fall back to the default
        PresenceConfig declares instead of being duplicated here."""
        return self.model_dump(exclude_none=True)


class SourceEntry(_Section):
    """One camera or microphone (requisito 21)."""

    source_id: str = Field(pattern=_SOURCE_ID_PATTERN)
    kind: SourceKind
    device: str | int
    source: SourceLocation = SourceLocation.LOCAL
    label: str | None = None
    enabled: bool = True
    sample_fps: float | None = Field(default=None, gt=0)

    @field_validator("source")
    @classmethod
    def reject_mcp(cls, value: SourceLocation) -> SourceLocation:
        if value == SourceLocation.MCP:
            raise ValueError(
                "source 'mcp' needs a tool injected by Janus (requisito 10) and is "
                "not available to the standalone runner"
            )
        return value

    @model_validator(mode="after")
    def check_device(self) -> Self:
        """A device the runner can never open fails at startup, not as an
        endless retry with backoff."""
        if self.kind == SourceKind.CAMERA and self.source == SourceLocation.LOCAL:
            if not str(self.device).isdigit():
                raise ValueError(
                    f"local camera '{self.source_id}' needs a numeric device index, "
                    f"got '{self.device}'"
                )
        if self.source == SourceLocation.RTSP:
            if not isinstance(self.device, str) or not self.device.strip():
                raise ValueError(f"stream source '{self.source_id}' needs a stream URL as device")
        return self

    def to_source_config(self) -> SourceConfig:
        return SourceConfig(
            source_id=self.source_id,
            kind=self.kind,
            source=self.source,
            device=str(self.device),
            label=self.label or self.source_id,
            enabled=self.enabled,
            sample_fps=self.sample_fps,
        )


class WakeWordSection(_Section):
    """The wake word service the microphone listens through. Having the
    section means voice activation is on; there is no default host or port
    because the service is the user's own (for example the openWakeWord that
    Home Assistant runs)."""

    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=_MAX_PORT)
    names: list[str] = Field(min_length=1)


class ReviewSection(_Section):
    """Local review page (requisito 39). Loopback only: the checklist
    requires the control interface to be authenticated and not exposed."""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(default=_DEFAULT_REVIEW_PORT, ge=1, le=_MAX_PORT)
    token_file: Path | None = None

    @field_validator("host")
    @classmethod
    def require_loopback(cls, value: str) -> str:
        if value not in _LOOPBACK_HOSTS:
            raise ValueError(f"review.host must be a loopback address, got '{value}'")
        return value

    @field_validator("token_file")
    @classmethod
    def expand_token_file(cls, value: Path | None) -> Path | None:
        return _expanded(value)


class EventsSection(_Section):
    """JSONL event log. `person_seen` fires per frame, so it is off by
    default; visits are the coarse events requisito 30 asks consumers for."""

    log_path: Path | None = None
    max_bytes: int = Field(default=_DEFAULT_EVENT_LOG_MAX_BYTES, gt=0)
    log_person_seen: bool = False

    @field_validator("log_path")
    @classmethod
    def expand_log_path(cls, value: Path | None) -> Path | None:
        return _expanded(value)


class HomeAssistantSection(_Section):
    """Where to send visit events (requisito 42). Having the section turns
    the sink on. The token lives in its own private file, never here."""

    url: str
    token_file: Path
    timeout_s: float = Field(default=DEFAULT_TIMEOUT_S, gt=0)
    queue_size: int = Field(default=DEFAULT_QUEUE_SIZE, gt=0)

    @field_validator("url")
    @classmethod
    def require_http_url(cls, value: str) -> str:
        if not value.startswith(_HA_SCHEMES) or len(value.split("://", 1)[1]) == 0:
            raise ValueError(
                f"home_assistant.url must start with http:// or https://, got '{value}'"
            )
        return value

    @field_validator("token_file")
    @classmethod
    def expand_token_file(cls, value: Path) -> Path:
        return value.expanduser()


def _check_source_ids(sources: list[SourceEntry]) -> None:
    ids = [entry.source_id for entry in sources]
    duplicated = sorted({source_id for source_id in ids if ids.count(source_id) > 1})
    if duplicated:
        raise ValueError(f"duplicated source_id: {', '.join(duplicated)}")


def _check_voice_activation(sources: list[SourceEntry], wakeword: WakeWordSection | None) -> None:
    has_microphone = any(entry.kind == SourceKind.MICROPHONE for entry in sources)
    if has_microphone and wakeword is None:
        raise ValueError("an enabled microphone source needs a [wakeword] section")
    if wakeword is not None and not has_microphone:
        raise ValueError("[wakeword] needs at least one enabled microphone source")


class RunnerConfig(_Section):
    state_dir: Path
    presence: PresenceSection
    sources: list[SourceEntry] = Field(min_length=1)
    wakeword: WakeWordSection | None = None
    review: ReviewSection = Field(default_factory=ReviewSection)
    events: EventsSection = Field(default_factory=EventsSection)
    home_assistant: HomeAssistantSection | None = None

    @field_validator("state_dir")
    @classmethod
    def expand_state_dir(cls, value: Path) -> Path:
        return value.expanduser()

    @model_validator(mode="after")
    def check_sources(self) -> Self:
        _check_source_ids(self.sources)
        enabled = [entry for entry in self.sources if entry.enabled]
        if not enabled:
            raise ValueError("at least one source must be enabled")
        _check_voice_activation(enabled, self.wakeword)
        return self

    def presence_config(self) -> PresenceConfig:
        return PresenceConfig(
            **self.presence.overrides(),
            sources=[entry.to_source_config() for entry in self.sources],
        )

    def event_log_path(self) -> Path:
        return self.events.log_path or self.state_dir / "presence" / "events.jsonl"

    def review_token_path(self) -> Path:
        return self.review.token_file or self.state_dir / "presence" / "review.token"


def _format_errors(error: ValidationError) -> str:
    lines = []
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"]) or "(root)"
        lines.append(f"  {location}: {item['msg']}")
    return "\n".join(lines)


def load_runner_config(path: Path) -> RunnerConfig:
    """Reads, validates and cross checks the runner config. Every failure
    is a RunnerConfigError naming the file, so the runner can refuse to
    start with a message instead of a traceback."""
    path = Path(path).expanduser()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RunnerConfigError(f"Cannot read runner config {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise RunnerConfigError(f"Runner config {path} is not valid TOML: {exc}") from exc

    try:
        config = RunnerConfig.model_validate(raw)
        config.presence_config()
    except ValidationError as exc:
        raise RunnerConfigError(f"Invalid runner config {path}:\n{_format_errors(exc)}") from exc
    except ValueError as exc:
        raise RunnerConfigError(f"Invalid runner config {path}: {exc}") from exc
    return config
