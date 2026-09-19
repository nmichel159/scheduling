import os
from datetime import timedelta
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Pydantic automaticky hľadá premenné s týmito názvami v systéme
    PROJECT_NAME: str = "Scheduling Project"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/scheduling")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "fallback_secret_for_dev")
    VITE_API_URL: str = os.getenv("VITE_API_URL", "http://localhost:8000")
    FRONTEND_ORIGINS: str = os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    SESSION_COOKIE_NAME: str = "scheduling_session"
    SESSION_TTL_HOURS: int = int(os.getenv("SESSION_TTL_HOURS", "12"))
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    AUTO_SEED: bool = os.getenv("AUTO_SEED", "false").lower() == "true"
    SEED_CONFIG: str = os.getenv("SEED_CONFIG", "config_1")
    SCHEDULE_SOLVER_TIME_LIMIT_SECONDS: int = max(
        1,
        int(os.getenv("SCHEDULE_SOLVER_TIME_LIMIT_SECONDS", "30")),
    )
    SCHEDULE_GENERATION_MAX_CONCURRENCY: int = max(
        1,
        int(os.getenv("SCHEDULE_GENERATION_MAX_CONCURRENCY", "1")),
    )
    AUTOMATIC_SCHEDULE_GENERATION_ENABLED: bool = (
        os.getenv("AUTOMATIC_SCHEDULE_GENERATION_ENABLED", "true").lower()
        == "true"
    )
    AUTOMATIC_SCHEDULE_GENERATION_TIMEZONE: str = os.getenv(
        "AUTOMATIC_SCHEDULE_GENERATION_TIMEZONE",
        "Europe/Bratislava",
    )
    AUTOMATIC_SCHEDULE_GENERATION_DAY: int = min(
        28,
        max(1, int(os.getenv("AUTOMATIC_SCHEDULE_GENERATION_DAY", "21"))),
    )
    AUTOMATIC_SCHEDULE_GENERATION_HOUR: int = min(
        23,
        max(0, int(os.getenv("AUTOMATIC_SCHEDULE_GENERATION_HOUR", "20"))),
    )
    AUTOMATIC_SCHEDULE_GENERATION_POLL_SECONDS: int = max(
        1,
        int(os.getenv("AUTOMATIC_SCHEDULE_GENERATION_POLL_SECONDS", "60")),
    )

    # --- Outgoing mail -------------------------------------------------
    # An unset SMTP_HOST is not a misconfiguration: local and test runs are
    # expected to have no mail server, and MAIL_DRY_RUN keeps the whole send
    # path exercised while the message only reaches the log.
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    SMTP_USE_SSL: bool = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
    SMTP_TIMEOUT_SECONDS: int = max(1, int(os.getenv("SMTP_TIMEOUT_SECONDS", "20")))
    MAIL_FROM: str = os.getenv("MAIL_FROM", "")
    MAIL_FROM_NAME: str = os.getenv("MAIL_FROM_NAME", "Rozpisy")
    MAIL_DRY_RUN: bool = os.getenv("MAIL_DRY_RUN", "false").lower() == "true"

    class Config:
        case_sensitive = True

settings = Settings()


def session_ttl() -> timedelta:
    return timedelta(hours=settings.SESSION_TTL_HOURS)
