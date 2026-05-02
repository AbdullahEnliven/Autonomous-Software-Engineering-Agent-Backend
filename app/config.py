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
    
    # Groq Fallback (Multiple keys supported, comma separated)
    GROQ_API_KEYS: str = ""
    GROQ_API_KEY: str = ""  # Left for backwards compatibility
    GROQ_LLM_MODEL: str = "llama-3.3-70b-versatile"

    # Image Personalization
    PEXELS_API_KEY: str = ""
    
    # GitHub OAuth
    GITHUB_CLIENT_ID: str = "your-github-client-id"
    GITHUB_CLIENT_SECRET: str = "your-github-client-secret"
    GITHUB_REDIRECT_URI: str = "http://localhost:5173/auth/github/callback"
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = "your-google-client-id"
    GOOGLE_CLIENT_SECRET: str = "your-google-client-secret"
    
    # Email & SMTP Settings
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@asea.app"
    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    CONTACT_EMAIL: str = "" # Email address to receive contact form submissions
    STORAGE_PATH: str = "/tmp/asea/projects"
    ARTIFACT_PATH: str = "/tmp/asea/artifacts"
    USER_PROJECTS_DIR: str = ""
    TEMPLATE_DIR: str = ""
    
    # Deployment
    DEPLOYMENT_MODE: str = "local"  # "local" or "production"
    LOCAL_DEPLOYMENT_PORT: int = 3000  # Port for local served projects
    DEPLOYMENT_DOMAIN: str = "enliven-app.com"  # Domain for production

    # Vercel deployment (single account used for all user projects)
    VERCEL_TOKEN: str = ""
    VERCEL_SCOPE: str = ""  # Optional team/user scope slug
    VERCEL_TEAM_ID: str = ""  # Optional team id
    VERCEL_PROJECT_PREFIX: str = "asea"
    
    # Monitoring
    SENTRY_DSN: str = ""
    FRONTEND_URL: str = "http://localhost:5173"
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:8000", "http://localhost:3000"]
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
