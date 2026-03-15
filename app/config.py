from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    APP_ENV: str = "development"
    SECRET_KEY: str = "your-secret-key-here"  # Default for dev, override in prod
    ENCRYPTION_KEY: str = "your-aes-256-key-here"
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/asea"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Gemini / Google
    GEMINI_API_KEY: str = "your-gemini-key"
    GOOGLE_API_KEY: str = "your-google-api-key"
    
    # Groq Fallback
    GROQ_API_KEY: str = ""
    GROQ_LLM_MODEL: str = "llama-3.3-70b-versatile"
    
    # GitHub OAuth
    GITHUB_CLIENT_ID: str = "your-github-client-id"
    GITHUB_CLIENT_SECRET: str = "your-github-client-secret"
    GITHUB_REDIRECT_URI: str = "http://localhost:8000/api/v1/integrations/github/callback"
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = "your-google-client-id"
    GOOGLE_CLIENT_SECRET: str = "your-google-client-secret"
    
    # Email
    RESEND_API_KEY: str = "your-resend-key"
    EMAIL_FROM: str = "noreply@asea.app"
    
    # Storage
    STORAGE_PATH: str = "/tmp/asea/projects"
    ARTIFACT_PATH: str = "/tmp/asea/artifacts"
    
    # Monitoring
    SENTRY_DSN: str = ""
    
    # Frontend
    FRONTEND_URL: str = "http://localhost:5173"
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:8000"]
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
