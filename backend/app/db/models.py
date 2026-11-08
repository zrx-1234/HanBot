from sqlalchemy import Boolean, Float, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> Mapped[int]:
    return mapped_column(Integer, server_default=func.strftime("%s", "now"))


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[int] = _now()


class LoginLogRow(Base):
    __tablename__ = "login_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String(64))
    ok: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[int] = _now()


class SettingsRow(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String)  # JSON 编码


class LlmSourceRow(Base):
    __tablename__ = "llm_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    format: Mapped[str] = mapped_column(String(16))  # openai / anthropic
    base_url: Mapped[str] = mapped_column(String(256))
    api_key_encrypted: Mapped[str] = mapped_column(String(512))
    # JSON: [{"name": 模型名, "price_in": 输入单价, "price_out": 输出单价}]（每百万 token 美元）
    models: Mapped[str] = mapped_column(String)
    priority: Mapped[int] = mapped_column(Integer, default=100)  # 数字越小优先级越高
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok / degraded
    cooldown_until: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(String)


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[int] = _now()
    updated_at: Mapped[int] = _now()
    dir_path: Mapped[str] = mapped_column(String(512))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_uuid: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[str | None] = mapped_column(String)  # JSON
    created_at: Mapped[int] = _now()


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    session_uuid: Mapped[str] = mapped_column(String(36), index=True)
    # queued / running / awaiting / done / stopped / failed
    status: Mapped[str] = mapped_column(String(16), default="queued")
    title: Mapped[str] = mapped_column(String(256), default="")
    origin: Mapped[str] = mapped_column(String(16), default="user")  # user / cron（缺口#2）
    created_at: Mapped[int] = _now()
    started_at: Mapped[int | None] = mapped_column(Integer)
    ended_at: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate: Mapped[float] = mapped_column(Float, default=0.0)


class TaskStepRow(Base):
    __tablename__ = "task_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_uuid: Mapped[str] = mapped_column(String(36), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    # llm_call / tool_call / tool_result / confirm_request / user_reply
    # / model_switch / error / note
    type: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)  # JSON，按 type 存不同结构
    created_at: Mapped[int] = _now()


class AbilityRow(Base):
    __tablename__ = "abilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(8), default="skill")  # skill / mcp
    name: Mapped[str] = mapped_column(String(128))
    desc: Mapped[str | None] = mapped_column(String(512))
    install_path: Mapped[str] = mapped_column(String(512))
    global_active: Mapped[bool] = mapped_column(Boolean, default=False)
    installed_at: Mapped[int] = _now()
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class MemoryRow(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    layer: Mapped[str] = mapped_column(String(16))  # core / profile / lessons / digest
    title: Mapped[str] = mapped_column(String(256))
    content: Mapped[str] = mapped_column(Text)  # Markdown
    tags: Mapped[str | None] = mapped_column(String)  # JSON
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/pending/archived
    source_task_uuid: Mapped[str | None] = mapped_column(String(36))
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = _now()
    updated_at: Mapped[int] = _now()


class UsageLogRow(Base):
    __tablename__ = "usage_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_uuid: Mapped[str | None] = mapped_column(String(36), index=True)
    source_id: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(64))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    # 缓存读写单列（缺口#1）：缓存读约一折价，不区分则成本估算高估数倍
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[int] = _now()


class NotificationRow(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_uuid: Mapped[str | None] = mapped_column(String(36), index=True)
    level: Mapped[str] = mapped_column(String(16))  # blocking / info / silent
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="sent")  # sent / read
    created_at: Mapped[int] = _now()


class CredentialRow(Base):
    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    site: Mapped[str | None] = mapped_column(String(256))
    secret_encrypted: Mapped[str] = mapped_column(String(512))
    note: Mapped[str | None] = mapped_column(String(512))
