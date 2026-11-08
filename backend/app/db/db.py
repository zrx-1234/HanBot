"""数据库层。

两套引擎（同一 SQLite 文件，WAL 支持多连接）：
- 同步引擎 + session_scope：迁移期（init_db/alembic）与测试直查用；
- 异步引擎 + asession_scope：运行时路由一律用它（DEVLOG 会话1裁定：M2 切 async）。

init_db 由 create_all（M1 过渡）改为 alembic 迁移驱动：
- 全新库：从头跑全部迁移；
- M1 遗留库（有 users、无 alembic_version）：先 stamp 到基线 0001 再升级。
"""

import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import alembic.command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_engines: dict[str, Engine] = {}
_session_factories: dict[str, sessionmaker[Session]] = {}
_async_engines: dict[str, AsyncEngine] = {}
_async_session_factories: dict[str, async_sessionmaker[AsyncSession]] = {}


def _set_pragma(dbapi_conn) -> None:  # type: ignore[no-untyped-def]
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def _make_engine(settings: Settings) -> Engine:
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _):  # type: ignore[no-untyped-def]
        _set_pragma(dbapi_conn)

    return engine


def _make_async_engine(settings: Settings) -> AsyncEngine:
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _):  # type: ignore[no-untyped-def]
        _set_pragma(dbapi_conn)

    return engine


def get_engine(settings: Settings) -> Engine:
    key = str(settings.db_path)
    if key not in _engines:
        _engines[key] = _make_engine(settings)
    return _engines[key]


def get_session_factory(settings: Settings) -> sessionmaker[Session]:
    key = str(settings.db_path)
    if key not in _session_factories:
        _session_factories[key] = sessionmaker(bind=get_engine(settings))
    return _session_factories[key]


def get_async_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    key = str(settings.db_path)
    if key not in _async_session_factories:
        if key not in _async_engines:
            _async_engines[key] = _make_async_engine(settings)
        _async_session_factories[key] = async_sessionmaker(bind=_async_engines[key])
    return _async_session_factories[key]


@contextmanager
def session_scope(settings: Settings) -> Iterator[Session]:
    """同步会话：仅供迁移期直查与测试断言使用，路由代码禁用。"""
    s = get_session_factory(settings)()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


@asynccontextmanager
async def asession_scope(settings: Settings) -> AsyncIterator[AsyncSession]:
    """异步会话：运行时路由的统一入口，离开作用域自动提交/回滚。"""
    s = get_async_session_factory(settings)()
    try:
        yield s
        await s.commit()
    except Exception:
        await s.rollback()
        raise
    finally:
        await s.close()


def _needs_baseline_stamp(db_path: Path) -> bool:
    """M1 遗留库判定：有 users 表但没有 alembic_version（create_all 时代产物）。"""
    if not db_path.exists():
        return False
    con = sqlite3.connect(db_path)
    try:
        tables = {
            r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        con.close()
    return "alembic_version" not in tables and "users" in tables


def init_db(settings: Settings) -> None:
    """建库/升级到最新迁移。幂等：已到 head 的库再跑无副作用。"""
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    if _needs_baseline_stamp(db_path):
        alembic.command.stamp(cfg, "0001")
    alembic.command.upgrade(cfg, "head")
