from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import get_settings
from app.models.orm import Base


def _ensure_data_dir() -> None:
    settings = get_settings()
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)


def get_engine():
    _ensure_data_dir()
    settings = get_settings()
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(settings.database_url, connect_args=connect_args)


_engine = None
SessionLocal = sessionmaker(autocommit=False, autoflush=False)


def init_db() -> None:
    global _engine
    _engine = get_engine()
    Base.metadata.create_all(bind=_engine)
    SessionLocal.configure(bind=_engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    global _engine
    if _engine is None:
        init_db()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
