import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Pydantic automaticky hľadá premenné s týmito názvami v systéme
    PROJECT_NAME: str = "Scheduling Project"
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "fallback_secret_for_dev")
    VITE_API_URL: str = os.getenv("VITE_API_URL", "http://localhost:8000")

    class Config:
        case_sensitive = True

settings = Settings()