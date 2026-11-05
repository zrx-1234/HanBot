import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    secret: str
    initial_username: str
    initial_password: str
    secure_cookies: bool = True

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
