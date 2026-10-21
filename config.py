from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator

BASE_DIR = Path(__file__).resolve().parent


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Schwab API
    SCHWAB_APP_KEY: str
    SCHWAB_APP_SECRET: str
    SCHWAB_ACCOUNT_HASH: str = ""
    SCHWAB_TOKEN_PATH: str = str(BASE_DIR / "schwab_token.json")
    SCHWAB_CALLBACK_URL: str = "https://127.0.0.1:8182"

    # Database
    DB_PATH: str = "/var/lib/tqqq-bot/tqqq.db"

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_PATH: str = "/var/log/tqqq-bot/bot.log"

    # Notifications (optional)
    DISCORD_WEBHOOK_URL: str = ""

    # Trading
    DRY_RUN: bool = True
    SMA_PERIOD: int = 200
    TICKER: str = "TQQQ"
    SAFE_TICKER: str = "BIL"

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid:
            raise ValueError(f"LOG_LEVEL must be one of {valid}")
        return v.upper()

    @model_validator(mode="after")
    def validate_path_directories(self) -> "Config":
        checks = {
            "SCHWAB_TOKEN_PATH": self.SCHWAB_TOKEN_PATH,
            "DB_PATH": self.DB_PATH,
            "LOG_PATH": self.LOG_PATH,
        }
        missing = [
            f"  {name}={p!r}  →  parent directory '{Path(p).parent}' does not exist"
            for name, p in checks.items()
            if not Path(p).parent.exists()
        ]
        if missing:
            raise ValueError(
                "The following config paths point to directories that don't exist:\n"
                + "\n".join(missing)
                + "\nCreate the directories or override the paths in your .env file."
            )
        return self


config = Config()
