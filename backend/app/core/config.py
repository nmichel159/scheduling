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
    # Vercel deployment URLs change for preview deployments. A fixed list can
    # still be supplied with FRONTEND_ORIGINS for a stricter production setup.
    FRONTEND_ORIGIN_REGEX: str = os.getenv("FRONTEND_ORIGIN_REGEX", r"^https://[a-z0-9.-]+\.vercel\.app$")
    SESSION_COOKIE_NAME: str = "scheduling_session"
    SESSION_TTL_HOURS: int = int(os.getenv("SESSION_TTL_HOURS", "12"))
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"

    class Config:
        case_sensitive = True

settings = Settings()


def session_ttl() -> timedelta:
    return timedelta(hours=settings.SESSION_TTL_HOURS)
