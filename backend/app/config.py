import os
from dataclasses import dataclass
from pathlib import Path

# 出现在 git 仓库或示例文件里的已知值，secure 模式一律拒启
_INSECURE_SECRETS = {"", "dev-secret-change-me", "please-change-me"}
_INSECURE_PASSWORDS = {"", "dev-password", "please-change-me"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    secret: str
    initial_username: str
    initial_password: str
    secure_cookies: bool = True
    lockout_threshold: int = 5
    lockout_seconds: int = 900

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.environ.get("HANBOT_DATA_DIR", "./data")),
            db_path=Path(os.environ.get("HANBOT_DB_PATH", "./data/db/hanbot.db")),
            secret=os.environ.get("HANBOT_SECRET", "dev-secret-change-me"),
            initial_username=os.environ.get("HANBOT_USERNAME", "han"),
            initial_password=os.environ.get("HANBOT_INITIAL_PASSWORD", ""),
            secure_cookies=os.environ.get("HANBOT_SECURE_COOKIES", "true").lower() == "true",
        )

    def validate_secure(self) -> None:
        """secure_cookies=True（生产/HTTPS）时的启动前检查：弱密钥或默认口令直接拒启。

        dev（secure_cookies=False）不做强约束，保住本地开箱即用。
        """
        if not self.secure_cookies:
            return
        problems: list[str] = []
        if self.secret in _INSECURE_SECRETS or len(self.secret) < 32:
            problems.append("HANBOT_SECRET 必须是 32 字符以上的随机串（当前为默认值/过短）")
        if self.initial_password in _INSECURE_PASSWORDS:
            problems.append("HANBOT_INITIAL_PASSWORD 不能为空或默认值")
        if problems:
            raise RuntimeError("生产模式启动检查未通过：" + "；".join(problems))
