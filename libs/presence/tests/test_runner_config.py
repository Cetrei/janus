"""Runner config (requisito 39): TOML validated by Pydantic, cross checked."""

from __future__ import annotations

from pathlib import Path

import pytest

from janus_presence.models import SourceKind, SourceLocation
from janus_presence.runner_config import RunnerConfigError, load_runner_config

CAMERA = """
[[sources]]
source_id = "cuarto"
kind = "camera"
device = 3
sample_fps = 4
"""

MICROPHONE = """
[[sources]]
source_id = "mic-cuarto"
kind = "microphone"
device = "default"
"""

WAKEWORD = """
[wakeword]
host = "127.0.0.1"
port = 10400
names = ["ok_nabu"]
"""


def write_config(tmp_path: Path, body: str, presence: str | None = None) -> Path:
    presence = presence or "match_threshold = 0.6\nmatch_threshold_ambiguous = 1.2\n"
    text = f'state_dir = "{(tmp_path / "state").as_posix()}"\n[presence]\n{presence}{body}'
    path = tmp_path / "presence.toml"
    path.write_text(text, encoding="utf-8")
    return path


class TestValidConfig:
    def test_minimal_config_loads_and_keeps_presence_defaults(self, tmp_path):
        config = load_runner_config(write_config(tmp_path, CAMERA))

        presence = config.presence_config()

        assert presence.match_threshold == 0.6
        assert presence.match_threshold_ambiguous == 1.2
        assert presence.visit_gap_s == 30
        assert presence.forget_after_days == 30

    def test_values_set_in_the_file_override_the_defaults(self, tmp_path):
        presence = "match_threshold = 0.6\nmatch_threshold_ambiguous = 1.2\nvisit_gap_s = 45\n"

        config = load_runner_config(write_config(tmp_path, CAMERA, presence))

        assert config.presence_config().visit_gap_s == 45

    def test_sources_become_source_configs_with_a_string_device(self, tmp_path):
        config = load_runner_config(write_config(tmp_path, CAMERA))

        source = config.presence_config().sources[0]

        assert source.source_id == "cuarto"
        assert source.kind == SourceKind.CAMERA
        assert source.source == SourceLocation.LOCAL
        assert source.device == "3"
        assert source.label == "cuarto"
        assert source.sample_fps == 4

    def test_camera_and_microphone_with_wakeword_are_accepted(self, tmp_path):
        config = load_runner_config(write_config(tmp_path, CAMERA + MICROPHONE + WAKEWORD))

        assert config.wakeword is not None
        assert config.wakeword.names == ["ok_nabu"]

    def test_paths_default_under_the_state_dir(self, tmp_path):
        config = load_runner_config(write_config(tmp_path, CAMERA))

        assert config.event_log_path() == tmp_path / "state" / "presence" / "events.jsonl"
        assert config.review_token_path() == tmp_path / "state" / "presence" / "review.token"

    def test_person_seen_logging_is_off_by_default(self, tmp_path):
        config = load_runner_config(write_config(tmp_path, CAMERA))

        assert config.events.log_person_seen is False


class TestInvalidConfig:
    def test_missing_file_is_a_config_error(self, tmp_path):
        with pytest.raises(RunnerConfigError, match="Cannot read"):
            load_runner_config(tmp_path / "nope.toml")

    def test_broken_toml_is_a_config_error(self, tmp_path):
        path = tmp_path / "presence.toml"
        path.write_text("this is = = not toml", encoding="utf-8")

        with pytest.raises(RunnerConfigError, match="not valid TOML"):
            load_runner_config(path)

    def test_match_thresholds_have_no_default(self, tmp_path):
        path = write_config(tmp_path, CAMERA, presence="visit_gap_s = 30\n")

        with pytest.raises(RunnerConfigError, match="match_threshold"):
            load_runner_config(path)

    def test_ambiguous_threshold_must_be_above_the_main_one(self, tmp_path):
        presence = "match_threshold = 1.2\nmatch_threshold_ambiguous = 0.6\n"

        with pytest.raises(RunnerConfigError, match="ambiguous"):
            load_runner_config(write_config(tmp_path, CAMERA, presence))

    def test_unknown_key_is_rejected_so_typos_do_not_pass(self, tmp_path):
        presence = "match_threshold = 0.6\nmatch_threshold_ambiguous = 1.2\nvisit_gap = 45\n"

        with pytest.raises(RunnerConfigError, match="visit_gap"):
            load_runner_config(write_config(tmp_path, CAMERA, presence))

    def test_duplicated_source_ids_are_rejected(self, tmp_path):
        with pytest.raises(RunnerConfigError, match="duplicated source_id"):
            load_runner_config(write_config(tmp_path, CAMERA + CAMERA))

    def test_source_id_cannot_escape_its_directory(self, tmp_path):
        body = CAMERA.replace("cuarto", "../evil")

        with pytest.raises(RunnerConfigError, match="source_id"):
            load_runner_config(write_config(tmp_path, body))

    def test_mcp_sources_are_not_available_to_the_runner(self, tmp_path):
        body = CAMERA + 'source = "mcp"\n'

        with pytest.raises(RunnerConfigError, match="injected by Janus"):
            load_runner_config(write_config(tmp_path, body))

    def test_at_least_one_source_must_be_enabled(self, tmp_path):
        body = CAMERA + "enabled = false\n"

        with pytest.raises(RunnerConfigError, match="at least one source"):
            load_runner_config(write_config(tmp_path, body))

    def test_microphone_without_wakeword_is_rejected(self, tmp_path):
        with pytest.raises(RunnerConfigError, match=r"\[wakeword\]"):
            load_runner_config(write_config(tmp_path, CAMERA + MICROPHONE))

    def test_wakeword_without_microphone_is_rejected(self, tmp_path):
        with pytest.raises(RunnerConfigError, match="microphone"):
            load_runner_config(write_config(tmp_path, CAMERA + WAKEWORD))

    def test_wakeword_needs_at_least_one_name(self, tmp_path):
        body = CAMERA + MICROPHONE + WAKEWORD.replace('["ok_nabu"]', "[]")

        with pytest.raises(RunnerConfigError, match="names"):
            load_runner_config(write_config(tmp_path, body))

    def test_review_page_must_stay_on_loopback(self, tmp_path):
        body = CAMERA + '[review]\nhost = "0.0.0.0"\n'

        with pytest.raises(RunnerConfigError, match="loopback"):
            load_runner_config(write_config(tmp_path, body))
