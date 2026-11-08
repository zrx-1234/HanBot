"""M2 收编 alembic（DEVLOG 会话1裁定）的测试。

init_db 的语义从 create_all 改为「迁移驱动」：
- 全新库：从头跑全部迁移；
- M1 时代的库（只有 users/login_log、无 alembic_version）：先 stamp 基线再升级；
- 迁移产物必须与 Base.metadata 一致（防模型与迁移漂移）。
"""

import sqlite3

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.config import Settings
from app.db import init_db
from app.db.models import Base

_ALL_TABLES = {
    "alembic_version",
    "users",
    "login_log",
    "settings",
    "llm_sources",
    "sessions",
    "messages",
    "tasks",
    "task_steps",
    "abilities",
    "memories",
    "usage_log",
    "notifications",
    "credentials",
}


def _table_names(db_path) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        return {
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        con.close()


def test_fresh_db_creates_all_tables(settings: Settings):
    init_db(settings)
    assert _ALL_TABLES <= _table_names(settings.db_path)


def test_legacy_m1_db_is_stamped_and_upgraded(tmp_path):
    """模拟 M1 遗留库：只有两张基线表（create_all 时代产物）。

    init_db 应 stamp 基线后增量升级，且不动已有数据。
    """
    db = tmp_path / "legacy.db"
    con = sqlite3.connect(db)
    con.execute(
        """CREATE TABLE users (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(64) NOT NULL,
            password_hash VARCHAR(256) NOT NULL,
            created_at INTEGER NOT NULL
        )"""
    )
    con.execute(
        """CREATE TABLE login_log (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            ip VARCHAR(64) NOT NULL,
            ok BOOLEAN NOT NULL,
            created_at INTEGER NOT NULL
        )"""
    )
    con.execute(
        "INSERT INTO users (username, password_hash, created_at) VALUES ('han', 'x', 1)"
    )
    con.commit()
    con.close()

    st = Settings(
        data_dir=tmp_path,
        db_path=db,
        secret="s",
        initial_username="han",
        initial_password="pw",
        secure_cookies=False,
    )
    init_db(st)

    assert _ALL_TABLES <= _table_names(db)
    # alembic 版本 = 最新
    con = sqlite3.connect(db)
    try:
        (version,) = con.execute("SELECT version_num FROM alembic_version").fetchone()
        rows = con.execute("SELECT username, password_hash FROM users").fetchall()
    finally:
        con.close()
    assert version == "0002"
    assert rows == [("han", "x")]


def test_repeated_init_db_is_idempotent(settings: Settings):
    init_db(settings)
    init_db(settings)  # 幂等：已到 head 的库再 init 不炸也不回滚
    assert _ALL_TABLES <= _table_names(settings.db_path)


def test_migrations_match_models(settings: Settings):
    """迁移建出的结构必须与 ORM 模型一致——防「改了模型忘写迁移」的漂移。"""
    init_db(settings)
    engine = create_engine(f"sqlite:///{settings.db_path}")
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            diff = compare_metadata(ctx, Base.metadata)
        assert diff == []
    finally:
        engine.dispose()
