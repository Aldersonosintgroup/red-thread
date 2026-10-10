import json
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.core import config, vault

PASSPHRASE = "correct horse battery"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A throwaway data folder with a plaintext database, evidence files, an
    API key in the settings file, and a leftover plaintext DB backup."""
    uploads = tmp_path / "uploads" / "case1"
    uploads.mkdir(parents=True)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "app_settings.json")
    monkeypatch.setattr(vault, "PASSPHRASE_KDF", {"n": 2 ** 10, "r": 8, "p": 1})  # fast tests
    monkeypatch.setattr(vault, "RECOVERY_KDF", {"n": 2 ** 10, "r": 8, "p": 1})
    monkeypatch.setattr(config.settings, "anthropic_api_key", "")
    vault.lock()
    vault._state.failed_attempts = 0

    con = sqlite3.connect(tmp_path / "redthread.db")
    con.execute("CREATE TABLE subjects (full_name TEXT)")
    con.executemany("INSERT INTO subjects VALUES (?)", [("Maria Example",), ("Second Subject",)])
    con.commit()
    con.close()
    (tmp_path / "redthread.db.backup-before-migration").write_bytes((tmp_path / "redthread.db").read_bytes())
    (uploads / "0000_scan.jpg").write_bytes(b"\xff\xd8JPEG evidence Maria")
    (uploads / "0001_file.pdf").write_bytes(b"%PDF-1.4 evidence")
    (tmp_path / "app_settings.json").write_text(json.dumps({"ai_provider": "claude", "anthropic_api_key": "sk-ant-secret"}))
    yield tmp_path
    vault.lock()


def _convert():
    vault.convert_database()
    vault.convert_files()
    vault.convert_secrets()
    return vault.remove_plaintext_leftovers()


def test_enable_converts_everything_and_leaves_no_plaintext(data_dir):
    recovery = vault.enable(PASSPHRASE)
    assert re.fullmatch(r"([A-Z2-7]{4}-){7}[A-Z2-7]{4}", recovery)
    removed = _convert()

    db_bytes = (data_dir / "redthread.db").read_bytes()
    assert not db_bytes.startswith(vault.SQLITE_HEADER) and b"Maria" not in db_bytes
    assert removed == ["redthread.db.backup-before-migration"]
    assert not (data_dir / "redthread.db.backup-before-migration").exists()

    scan = data_dir / "uploads" / "case1" / "0000_scan.jpg"
    assert scan.read_bytes().startswith(vault.FILE_MAGIC) and b"Maria" not in scan.read_bytes()
    assert vault.read_evidence(scan) == b"\xff\xd8JPEG evidence Maria"

    settings_file = json.loads((data_dir / "app_settings.json").read_text())
    assert "anthropic_api_key" not in settings_file and settings_file["ai_provider"] == "claude"
    vault_text = (data_dir / "vault.json").read_text()
    assert "sk-ant-secret" not in vault_text and PASSPHRASE not in vault_text
    vault.load_secrets_into_settings()
    assert config.settings.anthropic_api_key == "sk-ant-secret"


def test_encrypted_database_opens_only_with_the_key(data_dir):
    import sqlcipher3

    vault.enable(PASSPHRASE)
    _convert()
    con = sqlcipher3.dbapi2.connect(str(data_dir / "redthread.db"))
    con.execute(f"PRAGMA key = \"x'{vault.db_key_hex()}'\"")
    assert sorted(r[0] for r in con.execute("SELECT full_name FROM subjects")) == ["Maria Example", "Second Subject"]
    con.close()
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(data_dir / "redthread.db").execute("SELECT * FROM subjects").fetchall()


def test_lock_unlock_and_wrong_passphrase(data_dir):
    vault.enable(PASSPHRASE)
    _convert()
    vault.lock()
    assert vault.is_locked() and config.settings.anthropic_api_key == ""
    with pytest.raises(vault.VaultError):
        vault.read_evidence(data_dir / "uploads" / "case1" / "0000_scan.jpg")
    with pytest.raises(vault.WrongCredentials):
        vault.unlock("wrong passphrase!!")
    vault.unlock(PASSPHRASE)
    assert vault.read_evidence(data_dir / "uploads" / "case1" / "0001_file.pdf") == b"%PDF-1.4 evidence"


def test_recovery_key_replaces_a_forgotten_passphrase(data_dir):
    recovery = vault.enable(PASSPHRASE)
    vault.lock()
    with pytest.raises(vault.VaultError):
        vault.unlock(recovery_key=recovery)  # a new passphrase is required
    vault.unlock(recovery_key=recovery.lower().replace("-", " "), new_passphrase="brand new passphrase")
    vault.lock()
    with pytest.raises(vault.WrongCredentials):
        vault.unlock(PASSPHRASE)
    vault.unlock("brand new passphrase")


def test_change_passphrase(data_dir):
    vault.enable(PASSPHRASE)
    with pytest.raises(vault.WrongCredentials):
        vault.change_passphrase("not it at all", "another long passphrase")
    vault.change_passphrase(PASSPHRASE, "another long passphrase")
    vault.lock()
    vault.unlock("another long passphrase")


def test_short_passphrase_rejected(data_dir):
    with pytest.raises(vault.VaultError):
        vault.enable("short")
    assert not vault.is_enabled()


def test_interrupted_conversion_completes_on_next_unlock(data_dir):
    vault.enable(PASSPHRASE)
    vault.convert_files()  # "crash" before the database and secrets were converted
    vault.lock()
    vault.unlock(PASSPHRASE)
    assert vault.convert_files() == 0  # already done, idempotent
    assert vault.convert_database() is True
    assert vault.convert_database() is False
    vault.convert_secrets()
    assert "anthropic_api_key" not in json.loads((data_dir / "app_settings.json").read_text())


def test_write_evidence_encrypts_new_uploads_when_enabled(data_dir):
    target = data_dir / "uploads" / "case1" / "0002_new.png"
    vault.enable(PASSPHRASE)
    vault.write_evidence(target, b"new evidence")
    assert target.read_bytes().startswith(vault.FILE_MAGIC)
    assert vault.read_evidence(target) == b"new evidence"


def test_tampered_evidence_is_detected(data_dir):
    vault.enable(PASSPHRASE)
    vault.convert_files()
    scan = data_dir / "uploads" / "case1" / "0000_scan.jpg"
    data = bytearray(scan.read_bytes())
    data[-1] ^= 0x01
    scan.write_bytes(bytes(data))
    with pytest.raises(vault.VaultError, match="integrity"):
        vault.read_evidence(scan)


# ---------- HTTP guard (no lifespan: the real data folder is never opened) ----------

def _client():
    from app.main import app
    return TestClient(app, base_url="http://127.0.0.1:8420")


def test_foreign_website_origin_is_rejected():
    response = _client().get("/api/health", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_dns_rebinding_host_is_rejected():
    response = _client().get("/api/health", headers={"Host": "evil.example:8420"})
    assert response.status_code == 403


def test_app_origin_is_allowed():
    response = _client().get("/api/health", headers={"Origin": "http://tauri.localhost"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"


def test_data_routes_return_423_while_locked(data_dir):
    vault.enable(PASSPHRASE)
    vault.lock()
    client = _client()
    assert client.get("/api/cases").status_code == 423
    assert client.get("/api/vault/status").json()["locked"] is True
