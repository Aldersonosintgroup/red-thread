"""Database engine lifecycle. The engine is opened at startup for an
unencrypted database, or on unlock for an encrypted one (SQLCipher, keyed
from the vault), and closed again on lock so no key stays in a pool."""
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool

from app.core import vault

Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False)

_engine: Engine | None = None


class DatabaseLocked(Exception):
    pass


def open_engine() -> Engine:
    global _engine
    close_engine()
    path = vault.db_path().as_posix()
    if vault.is_enabled():
        # SQLAlchemy's SQLCipher dialect issues `pragma key="<password>"`,
        # so passing x'<hex>' supplies the raw 256-bit key directly (no
        # per-connection key derivation).
        url = URL.create("sqlite+pysqlcipher", password=f"x'{vault.db_key_hex()}'", database=path)
    else:
        url = f"sqlite:///{path}"
    # QueuePool explicitly: the SQLCipher dialect otherwise defaults to
    # SingletonThreadPool, which closes connections still in use by other
    # threads once more than 5 request threads touch the database (seen as
    # "Cannot operate on a closed database" and native crashes).
    _engine = create_engine(url, connect_args={"check_same_thread": False},
                            poolclass=QueuePool, pool_size=10, max_overflow=20)
    SessionLocal.configure(bind=_engine)
    return _engine


def close_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
    SessionLocal.configure(bind=None)


def get_engine() -> Engine:
    if _engine is None:
        raise DatabaseLocked("Database is not open")
    return _engine


def get_db():
    if _engine is None:
        raise DatabaseLocked("Database is not open")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
