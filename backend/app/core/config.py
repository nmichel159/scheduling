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

    class Config:
        case_sensitive = True

settings = Settings()


def session_ttl() -> timedelta:
    return timedelta(hours=settings.SESSION_TTL_HOURS)
