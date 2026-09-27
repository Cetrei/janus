from __future__ import annotations

import pytest
from conftest import make_enrollment

from janus_biometrics.errors import KeyUnavailable
from janus_biometrics.store import EncryptedTemplateStore

KEY_A = b"a" * 32
KEY_B = b"b" * 32


class TestSaveAndLoad:
    def test_round_trip_preserves_enrollment(self, tmp_state_dir):
        store = EncryptedTemplateStore(tmp_state_dir, KEY_A)
        enrollment = make_enrollment(kind="face", profile="owner")
        store.save(enrollment)

        loaded = store.load("face", "owner")

        assert loaded.kind == enrollment.kind
        assert loaded.profile == enrollment.profile
        assert loaded.model_id == enrollment.model_id
        assert loaded.embeddings == enrollment.embeddings
        assert loaded.centroid == enrollment.centroid

    def test_load_returns_none_when_not_enrolled(self, tmp_state_dir):
        store = EncryptedTemplateStore(tmp_state_dir, KEY_A)
        assert store.load("face", "owner") is None

    def test_stored_file_is_not_plaintext_json(self, tmp_state_dir):
        store = EncryptedTemplateStore(tmp_state_dir, KEY_A)
        store.save(make_enrollment(kind="face", profile="owner"))
        raw = (tmp_state_dir / "biometrics" / "face" / "owner.enc").read_bytes()
        assert b"embeddings" not in raw


class TestKeyValidation:
    def test_rejects_key_of_wrong_length(self, tmp_state_dir):
        with pytest.raises(KeyUnavailable):
            EncryptedTemplateStore(tmp_state_dir, b"too-short")


class TestWrongKeyRejection:
    def test_wrong_key_raises_on_decrypt(self, tmp_state_dir):
        store_a = EncryptedTemplateStore(tmp_state_dir, KEY_A)
        store_a.save(make_enrollment(kind="face", profile="owner"))

        store_b = EncryptedTemplateStore(tmp_state_dir, KEY_B)
        with pytest.raises(KeyUnavailable):
            store_b.load("face", "owner")


class TestTamperedFileRejection:
    def test_altered_ciphertext_raises(self, tmp_state_dir):
        store = EncryptedTemplateStore(tmp_state_dir, KEY_A)
        store.save(make_enrollment(kind="face", profile="owner"))

        path = tmp_state_dir / "biometrics" / "face" / "owner.enc"
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 0xFF
        path.write_bytes(bytes(raw))

        with pytest.raises(KeyUnavailable):
            store.load("face", "owner")


class TestDelete:
    def test_delete_removes_template(self, tmp_state_dir):
        store = EncryptedTemplateStore(tmp_state_dir, KEY_A)
        store.save(make_enrollment(kind="face", profile="owner"))
        store.delete("face", "owner")
        assert store.load("face", "owner") is None

    def test_delete_on_missing_template_does_not_raise(self, tmp_state_dir):
        store = EncryptedTemplateStore(tmp_state_dir, KEY_A)
        store.delete("face", "owner")

    def test_exists_reflects_store_state(self, tmp_state_dir):
        store = EncryptedTemplateStore(tmp_state_dir, KEY_A)
        assert not store.exists("face", "owner")
        store.save(make_enrollment(kind="face", profile="owner"))
        assert store.exists("face", "owner")
