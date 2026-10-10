"""Encryption at rest: the case database, the uploaded evidence files, and
the AI provider API keys.

Key hierarchy
-------------
A random 256-bit data key (DEK) encrypts everything. It is never stored in
the clear: vault.json holds it twice, wrapped (AES-256-GCM) under

* a key derived from the user's passphrase (scrypt, ~0.5 s per attempt), and
* a key derived from a one-time recovery key shown to the user once.

Changing the passphrase only re-wraps the DEK; nothing is re-encrypted.
From the DEK, separate subkeys (HKDF) are derived for the SQLCipher
database, the evidence files, and the stored API keys.

Crash safety
------------
vault.json is written *before* anything is converted, and every conversion
step (database export, file encryption, secret migration, plaintext
cleanup) is idempotent and re-run on every unlock. An interrupted
conversion therefore finishes on the next unlock instead of leaving data
unreadable. Evidence reads accept both encrypted and not-yet-converted
plaintext files for the same reason.
"""
import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core import config

logger = logging.getLogger("redthread.vault")

VAULT_VERSION = 1
FILE_MAGIC = b"RTENC1\x00"
SQLITE_HEADER = b"SQLite format 3\x00"
SECRET_FIELDS = config.SECRET_FIELDS
MIN_PASSPHRASE_LENGTH = 10
DEFAULT_AUTO_LOCK_MINUTES = 15

# scrypt cost for the passphrase. n=2**17 uses 128 MiB and ~0.5 s, which is
# what makes guessing passphrases from a stolen vault.json expensive.
PASSPHRASE_KDF = {"n": 2 ** 17, "r": 8, "p": 1}
# The recovery key is 160 random bits, so it needs no slow KDF to be safe.
RECOVERY_KDF = {"n": 2 ** 14, "r": 8, "p": 1}


class VaultError(Exception):
    pass


class WrongCredentials(VaultError):
    pass


def vault_path() -> Path:
    return config.DATA_DIR / "vault.json"


def db_path() -> Path:
    return config.DATA_DIR / "redthread.db"


# ---------- primitives ----------

def _scrypt(secret: str, salt: bytes, params: dict) -> bytes:
    return hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=params["n"], r=params["r"], p=params["p"],
                          maxmem=256 * 1024 * 1024, dklen=32)


def _subkey(dek: bytes, purpose: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=f"redthread/{purpose}".encode()).derive(dek)


def _seal(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def _open(key: bytes, blob: bytes, aad: bytes) -> bytes:
    return AESGCM(key).decrypt(blob[:12], blob[12:], aad)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text)


def _normalize_recovery_key(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalnum())


def _new_recovery_key() -> str:
    raw = base64.b32encode(secrets.token_bytes(20)).decode("ascii")  # 32 chars, no padding
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _shred(path: Path) -> None:
    """Overwrite then delete. On SSDs the old blocks may survive in the
    drive's spare area; full-disk encryption (BitLocker) covers that."""
    try:
        size = path.stat().st_size
        with path.open("r+b") as f:
            f.write(b"\x00" * size)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass
    path.unlink(missing_ok=True)


# ---------- state ----------

class _State:
    def __init__(self) -> None:
        self.dek: bytes | None = None
        self.last_activity = time.monotonic()
        self.failed_attempts = 0
        self.lock = threading.RLock()


_state = _State()


def is_enabled() -> bool:
    return vault_path().exists()


def is_unlocked() -> bool:
    return _state.dek is not None


def is_locked() -> bool:
    return is_enabled() and not is_unlocked()


def touch() -> None:
    _state.last_activity = time.monotonic()


def idle_seconds() -> float:
    return time.monotonic() - _state.last_activity


def _read_vault() -> dict:
    return json.loads(vault_path().read_text(encoding="utf-8"))


def _write_vault(data: dict) -> None:
    _atomic_write(vault_path(), json.dumps(data, indent=2).encode("utf-8"))


def auto_lock_minutes() -> int:
    if not is_enabled():
        return DEFAULT_AUTO_LOCK_MINUTES
    return int(_read_vault().get("auto_lock_minutes", DEFAULT_AUTO_LOCK_MINUTES))


def set_auto_lock_minutes(minutes: int) -> None:
    data = _read_vault()
    data["auto_lock_minutes"] = max(0, int(minutes))
    _write_vault(data)


def db_key_hex() -> str:
    if _state.dek is None:
        raise VaultError("Vault is locked")
    return _subkey(_state.dek, "database").hex()


# ---------- evidence files ----------

def _file_key() -> bytes:
    if _state.dek is None:
        raise VaultError("Vault is locked")
    return _subkey(_state.dek, "files")


def encrypt_bytes(data: bytes) -> bytes:
    return FILE_MAGIC + _seal(_file_key(), data, FILE_MAGIC)


def read_evidence(path: str | Path) -> bytes:
    """Read an evidence file, decrypting it if it is encrypted."""
    data = Path(path).read_bytes()
    if data.startswith(FILE_MAGIC):
        try:
            return _open(_file_key(), data[len(FILE_MAGIC):], FILE_MAGIC)
        except InvalidTag as exc:
            raise VaultError(f"Evidence file failed its integrity check: {Path(path).name}") from exc
    return data


def write_evidence(path: str | Path, data: bytes) -> None:
    """Write an evidence file, encrypted whenever the vault is enabled."""
    _atomic_write(Path(path), encrypt_bytes(data) if is_enabled() else data)


# ---------- secrets (API keys) ----------

def _load_secrets(data: dict) -> dict:
    blob = data.get("secrets")
    if not blob:
        return {}
    return json.loads(_open(_subkey(_state.dek, "secrets"), _unb64(blob), b"secrets"))


def save_secrets(values: dict) -> None:
    data = _read_vault()
    current = _load_secrets(data)
    current.update({k: v for k, v in values.items() if k in SECRET_FIELDS})
    data["secrets"] = _b64(_seal(_subkey(_state.dek, "secrets"), json.dumps(current).encode(), b"secrets"))
    _write_vault(data)


def _apply_secrets_to_settings(values: dict) -> None:
    for field in SECRET_FIELDS:
        setattr(config.settings, field, values.get(field, ""))


# ---------- lifecycle ----------

def _wrap_dek(dek: bytes, secret: str, params: dict) -> dict:
    salt = os.urandom(16)
    return {"salt": _b64(salt), "kdf": {"name": "scrypt", **params},
            "wrapped_key": _b64(_seal(_scrypt(secret, salt, params), dek, b"dek"))}


def _unwrap_dek(entry: dict, secret: str) -> bytes:
    params = {k: entry["kdf"][k] for k in ("n", "r", "p")}
    kek = _scrypt(secret, _unb64(entry["salt"]), params)
    return _open(kek, _unb64(entry["wrapped_key"]), b"dek")


def enable(passphrase: str) -> str:
    """Turn encryption on. Returns the recovery key, which is shown once and
    never stored. The caller must then run complete_conversion()."""
    with _state.lock:
        if is_enabled():
            raise VaultError("Encryption is already on")
        if len(passphrase) < MIN_PASSPHRASE_LENGTH:
            raise VaultError(f"Passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters")
        dek = secrets.token_bytes(32)
        recovery_key = _new_recovery_key()
        _write_vault({
            "version": VAULT_VERSION,
            "passphrase": _wrap_dek(dek, passphrase, PASSPHRASE_KDF),
            "recovery": _wrap_dek(dek, _normalize_recovery_key(recovery_key), RECOVERY_KDF),
            "auto_lock_minutes": DEFAULT_AUTO_LOCK_MINUTES,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        _state.dek = dek
        return recovery_key


def unlock(passphrase: str | None = None, recovery_key: str | None = None,
           new_passphrase: str | None = None) -> None:
    """Unlock with the passphrase, or with the recovery key plus a new
    passphrase (a forgotten passphrase is replaced, not recovered)."""
    with _state.lock:
        if not is_enabled():
            raise VaultError("Encryption is not on")
        if _state.failed_attempts >= 3:
            time.sleep(min(2 ** (_state.failed_attempts - 3), 30))  # slow down guessing
        data = _read_vault()
        try:
            if recovery_key:
                if not new_passphrase or len(new_passphrase) < MIN_PASSPHRASE_LENGTH:
                    raise VaultError(f"Choose a new passphrase of at least {MIN_PASSPHRASE_LENGTH} characters")
                dek = _unwrap_dek(data["recovery"], _normalize_recovery_key(recovery_key))
            else:
                dek = _unwrap_dek(data["passphrase"], passphrase or "")
        except InvalidTag as exc:
            _state.failed_attempts += 1
            raise WrongCredentials("Wrong passphrase" if not recovery_key else "Wrong recovery key") from exc
        _state.failed_attempts = 0
        if recovery_key:
            data["passphrase"] = _wrap_dek(dek, new_passphrase, PASSPHRASE_KDF)
            _write_vault(data)
        _state.dek = dek
        touch()


def change_passphrase(current: str, new: str) -> None:
    with _state.lock:
        if len(new) < MIN_PASSPHRASE_LENGTH:
            raise VaultError(f"New passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters")
        data = _read_vault()
        try:
            dek = _unwrap_dek(data["passphrase"], current)
        except InvalidTag as exc:
            raise WrongCredentials("Current passphrase is wrong") from exc
        data["passphrase"] = _wrap_dek(dek, new, PASSPHRASE_KDF)
        _write_vault(data)


def lock() -> None:
    with _state.lock:
        _state.dek = None
        _apply_secrets_to_settings({})


def load_secrets_into_settings() -> None:
    _apply_secrets_to_settings(_load_secrets(_read_vault()))


# ---------- conversion (idempotent) ----------

def _is_plaintext_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(16) == SQLITE_HEADER
    except OSError:
        return False


def _table_counts(conn) -> dict:
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def convert_database() -> bool:
    """Plaintext redthread.db -> SQLCipher, verified row-for-row before the
    plaintext is shredded. Must run with no open engine on the file."""
    import sqlcipher3

    path = db_path()
    if not _is_plaintext_sqlite(path):
        return False
    encrypted = path.with_name("redthread.db.encrypting")
    encrypted.unlink(missing_ok=True)
    key = db_key_hex()

    plain = sqlcipher3.dbapi2.connect(str(path))
    try:
        expected = _table_counts(plain)
        plain.execute(f"ATTACH DATABASE ? AS encrypted KEY \"x'{key}'\"", (str(encrypted),))
        plain.execute("SELECT sqlcipher_export('encrypted')")
        plain.execute("DETACH DATABASE encrypted")
    finally:
        plain.close()

    check = sqlcipher3.dbapi2.connect(str(encrypted))
    try:
        check.execute(f"PRAGMA key = \"x'{key}'\"")
        actual = _table_counts(check)
    finally:
        check.close()
    if actual != expected:
        encrypted.unlink(missing_ok=True)
        raise VaultError(f"Encrypted copy did not match the original database ({expected} vs {actual})")

    _shred(path)
    os.replace(encrypted, path)
    logger.info("Database encrypted (%d tables verified)", len(expected))
    return True


def convert_files() -> int:
    """Encrypt every not-yet-encrypted file under uploads/. Returns how many."""
    count = 0
    for path in config.UPLOAD_DIR.rglob("*"):
        if not path.is_file() or path.name.endswith(".tmp"):
            continue
        with path.open("rb") as f:
            if f.read(len(FILE_MAGIC)) == FILE_MAGIC:
                continue
        _atomic_write(path, encrypt_bytes(path.read_bytes()))
        count += 1
    return count


def convert_secrets() -> None:
    """Move API keys out of the plaintext settings file into the vault."""
    file = config.SETTINGS_FILE
    if not file.exists():
        return
    try:
        saved = json.loads(file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    plain_secrets = {k: saved[k] for k in SECRET_FIELDS if saved.get(k)}
    if plain_secrets:
        save_secrets(plain_secrets)
    if any(k in saved for k in SECRET_FIELDS):
        for k in SECRET_FIELDS:
            saved.pop(k, None)
        _atomic_write(file, json.dumps(saved, indent=2).encode("utf-8"))


def remove_plaintext_leftovers() -> list[str]:
    """Shred unencrypted copies the app itself left in its data folder."""
    removed = []
    for path in config.DATA_DIR.glob("redthread.db.backup*"):
        if _is_plaintext_sqlite(path):
            _shred(path)
            removed.append(path.name)
    return removed
