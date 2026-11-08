"""alembic 运行环境。

init_db() 程序化调用（backend 无 alembic.ini）：script_location 与
sqlalchemy.url 均由调用方 set_main_option 注入，这里只做标准 online 迁移。
SQLite 上 ALTER 受限，开 render_as_batch 供后续改表迁移使用。
"""

from alembic import context
from sqlalchemy import engine_from_config, pool


def run_migrations_online() -> None:
    connectable = engine_from_config(
        context.config.get_section(context.config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
