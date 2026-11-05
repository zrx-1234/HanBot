from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings

_engines: dict[str, Engine] = {}
_session_factories: dict[str, sessionmaker[Session]] = {}


def _make_engine(settings: Settings) -> Engine:
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _):  # type: ignore[no-untyped-def]
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def get_engine(settings: Settings) -> Engine:
    key = str(settings.db_path)
    if key not in _engines:
        _engines[key] = _make_engine(settings)
    return _engines[key]


def init_db(settings: Settings) -> None:
    from app.db import models

    models.Base.metadata.create_all(get_engine(settings))


def get_session_factory(settings: Settings) -> sessionmaker[Session]:
    key = str(settings.db_path)
    if key not in _session_factories:
        _session_factories[key] = sessionmaker(bind=get_engine(settings))
    return _session_factories[key]


@contextmanager
def session_scope(settings: Settings) -> Iterator[Session]:
    s = get_session_factory(settings)()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
