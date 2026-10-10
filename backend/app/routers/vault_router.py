"""Encryption controls: status, turn on, unlock, lock, change passphrase,
auto-lock timeout. These are the only data routes reachable while locked."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import database_lifecycle, vault
from app.services import queue_processor

router = APIRouter(prefix="/api/vault", tags=["vault"])


class VaultStatus(BaseModel):
    enabled: bool
    locked: bool
    auto_lock_minutes: int
    min_passphrase_length: int = vault.MIN_PASSPHRASE_LENGTH


class EnableRequest(BaseModel):
    passphrase: str


class EnableResponse(BaseModel):
    recovery_key: str
    files_encrypted: int
    removed_plaintext_copies: list[str]


class UnlockRequest(BaseModel):
    passphrase: str | None = None
    recovery_key: str | None = None
    new_passphrase: str | None = None


class ChangePassphraseRequest(BaseModel):
    current_passphrase: str
    new_passphrase: str


class AutoLockRequest(BaseModel):
    minutes: int


def _status() -> VaultStatus:
    return VaultStatus(enabled=vault.is_enabled(), locked=vault.is_locked(),
                       auto_lock_minutes=vault.auto_lock_minutes())


@router.get("/status", response_model=VaultStatus)
def status():
    return _status()


@router.post("/enable", response_model=EnableResponse)
def enable(payload: EnableRequest):
    if queue_processor.is_busy():
        raise HTTPException(409, "Wait for document extraction to finish before turning on encryption.")
    try:
        recovery_key = vault.enable(payload.passphrase)
    except vault.VaultError as exc:
        raise HTTPException(400, str(exc)) from exc
    report = database_lifecycle.convert_and_reopen()
    return EnableResponse(recovery_key=recovery_key, **report)


@router.post("/unlock", response_model=VaultStatus)
def unlock(payload: UnlockRequest):
    try:
        vault.unlock(payload.passphrase, payload.recovery_key, payload.new_passphrase)
    except vault.WrongCredentials as exc:
        raise HTTPException(401, str(exc)) from exc
    except vault.VaultError as exc:
        raise HTTPException(400, str(exc)) from exc
    database_lifecycle.convert_and_reopen()  # finishes any interrupted conversion
    return _status()


@router.post("/lock", response_model=VaultStatus)
def lock():
    if not vault.is_enabled():
        raise HTTPException(400, "Encryption is not on")
    database_lifecycle.lock()
    return _status()


@router.post("/change-passphrase", response_model=VaultStatus)
def change_passphrase(payload: ChangePassphraseRequest):
    try:
        vault.change_passphrase(payload.current_passphrase, payload.new_passphrase)
    except vault.WrongCredentials as exc:
        raise HTTPException(401, str(exc)) from exc
    except vault.VaultError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _status()


@router.put("/auto-lock", response_model=VaultStatus)
def set_auto_lock(payload: AutoLockRequest):
    if not vault.is_enabled():
        raise HTTPException(400, "Encryption is not on")
    vault.set_auto_lock_minutes(payload.minutes)
    return _status()
