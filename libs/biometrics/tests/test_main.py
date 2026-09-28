from __future__ import annotations

from conftest import make_enrollment

from janus_biometrics import __main__ as cli
from janus_biometrics.store import EncryptedTemplateStore

KEY = b"k" * 32


def _common_args(tmp_path) -> list[str]:
    return ["--state-dir", str(tmp_path / "state"), "--key-file", str(tmp_path / "key")]


class TestKeygen:
    def test_writes_a_32_byte_key(self, tmp_path):
        key_file = tmp_path / "key"
        rc = cli.main(["keygen", *_common_args(tmp_path)])
        assert rc == 0
        assert key_file.exists()
        assert len(key_file.read_bytes()) == 32

    def test_refuses_to_overwrite_without_force(self, tmp_path):
        key_file = tmp_path / "key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(KEY)

        rc = cli.main(["keygen", *_common_args(tmp_path)])

        assert rc == 1
        assert key_file.read_bytes() == KEY  # unchanged

    def test_force_overwrites_existing_key(self, tmp_path):
        key_file = tmp_path / "key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(KEY)

        rc = cli.main(["keygen", "--force", *_common_args(tmp_path)])

        assert rc == 0
        assert key_file.read_bytes() != KEY


class TestEnrollVoiceIsBlocked:
    def test_voice_enrollment_raises_biometrics_error(self, tmp_path):
        key_file = tmp_path / "key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(KEY)
        source_dir = tmp_path / "samples"
        source_dir.mkdir()

        rc = cli.main(
            [
                "enroll",
                "--kind",
                "voice",
                "--source",
                str(source_dir),
                *_common_args(tmp_path),
            ]
        )

        # main() catches BiometricsError and returns 1 rather than raising,
        # matching the CLI's real entrypoint behavior for the user.
        assert rc == 1


class TestEnrollFace:
    def test_calls_enroll_face_and_saves(self, tmp_path, monkeypatch):
        key_file = tmp_path / "key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(KEY)
        source_dir = tmp_path / "samples"
        source_dir.mkdir()
        (source_dir / "a.png").write_bytes(b"fake")

        fake_enrollment = make_enrollment(kind="face")
        monkeypatch.setattr(cli.enrollment, "enroll_face", lambda images, cache: fake_enrollment)

        rc = cli.main(
            ["enroll", "--kind", "face", "--source", str(source_dir), *_common_args(tmp_path)]
        )

        assert rc == 0
        store = EncryptedTemplateStore(tmp_path / "state", KEY)
        assert store.exists("face", "owner")


class TestListAndDelete:
    def test_list_reports_no_enrollments_when_empty(self, tmp_path, capsys):
        key_file = tmp_path / "key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(KEY)

        rc = cli.main(["list", *_common_args(tmp_path)])

        assert rc == 0
        assert "No enrollments found" in capsys.readouterr().out

    def test_list_reports_existing_enrollment(self, tmp_path, capsys):
        key_file = tmp_path / "key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(KEY)
        store = EncryptedTemplateStore(tmp_path / "state", KEY)
        store.save(make_enrollment(kind="face"))

        rc = cli.main(["list", *_common_args(tmp_path)])

        out = capsys.readouterr().out
        assert rc == 0
        assert "face/owner" in out

    def test_delete_removes_enrollment(self, tmp_path):
        key_file = tmp_path / "key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(KEY)
        store = EncryptedTemplateStore(tmp_path / "state", KEY)
        store.save(make_enrollment(kind="face"))

        rc = cli.main(["delete", "--kind", "face", *_common_args(tmp_path)])

        assert rc == 0
        assert not store.exists("face", "owner")

    def test_delete_missing_enrollment_returns_nonzero(self, tmp_path):
        key_file = tmp_path / "key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(KEY)

        rc = cli.main(["delete", "--kind", "face", *_common_args(tmp_path)])

        assert rc == 1


class TestMissingKey:
    def test_open_store_without_key_file_raises_biometrics_error(self, tmp_path):
        rc = cli.main(["list", *_common_args(tmp_path)])
        assert rc == 1


class TestCalibrateWithoutEnrollment:
    def test_raises_when_no_enrollment_exists(self, tmp_path):
        key_file = tmp_path / "key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(KEY)

        rc = cli.main(["calibrate", "--kind", "face", *_common_args(tmp_path)])

        assert rc == 1


class TestCalibrate:
    def test_calibrates_from_existing_enrollment(self, tmp_path, capsys):
        key_file = tmp_path / "key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(KEY)
        store = EncryptedTemplateStore(tmp_path / "state", KEY)
        enrollment_with_many_samples = make_enrollment(kind="face")
        store.save(enrollment_with_many_samples)

        rc = cli.main(["calibrate", "--kind", "face", *_common_args(tmp_path)])

        out = capsys.readouterr().out
        assert rc == 0
        assert "t_high" in out
        assert "t_low" in out
