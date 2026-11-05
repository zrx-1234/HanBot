from sqlalchemy import select

from app.config import Settings
from app.db import init_db, models, session_scope


def test_init_db_creates_users_table(settings: Settings):
    init_db(settings)
    # 能插入并按用户名查出——插入成功即表已建（不 断言模块常量）
    with session_scope(settings) as s:
        s.add(models.UserRow(username="alice", password_hash="x"))

    with session_scope(settings) as s:
        row = s.execute(
            select(models.UserRow).where(models.UserRow.username == "alice")
        ).scalar_one()
        assert row.password_hash == "x"


def test_login_log_roundtrip(settings: Settings):
    init_db(settings)
    with session_scope(settings) as s:
        s.add(models.LoginLogRow(ip="1.2.3.4", ok=True))
    with session_scope(settings) as s:
        rows = s.execute(select(models.LoginLogRow)).scalars().all()
        assert len(rows) == 1
        assert rows[0].ip == "1.2.3.4"
        assert rows[0].ok is True
