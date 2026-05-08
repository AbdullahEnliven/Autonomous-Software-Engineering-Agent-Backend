from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List
import json

class Settings(BaseSettings):
    APP_ENV: str = "development"
    SECRET_KEY: str = "your-secret-key-here"
    ENCRYPTION_KEY: str = "your-aes-256-key-here"
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/asea"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Gemini / Google
    GEMINI_API_KEY: str = "your-gemini-key"
    GOOGLE_API_KEY: str = "your-google-api-key"
    
    # Groq
    GROQ_API_KEYS: str = ""
    GROQ_API_KEY: str = ""
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
    
    # Email & SMTP
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@asea.app"
    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    CONTACT_EMAIL: str = ""
    STORAGE_PATH: str = "/tmp/asea/projects"
    ARTIFACT_PATH: str = "/tmp/asea/artifacts"
    USER_PROJECTS_DIR: str = ""
    TEMPLATE_DIR: str = ""
    
    # Deployment
    DEPLOYMENT_MODE: str = "local"
    LOCAL_DEPLOYMENT_PORT: int = 3000
    DEPLOYMENT_DOMAIN: str = "enliven-app.com"

    # Vercel
    VERCEL_TOKEN: str = ""
    VERCEL_SCOPE: str = ""
    VERCEL_TEAM_ID: str = ""
    VERCEL_PROJECT_PREFIX: str = "asea"
    
    # Monitoring
    SENTRY_DSN: str = ""
    FRONTEND_URL: str = "http://localhost:5173"

    # Stored as str so pydantic-settings never tries to JSON-parse it automatically.
    # The validator below converts it to List[str].
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:8000,http://localhost:3000"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, list):
            return ",".join(v)
        return str(v) if v else ""

    @property
    def cors_origins_list(self) -> List[str]:
        """Returns CORS_ORIGINS as a parsed list."""
        v = self.CORS_ORIGINS.strip()
        if not v:
            return []
        if v.startswith("["):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(i).strip() for i in parsed]
            except json.JSONDecodeError:
                pass
        return [o.strip() for o in v.split(",") if o.strip()]

    # Railway
    RAILWAY_PUBLIC_DOMAIN: str = ""
    RAILWAY_STATIC_URL: str = ""

    @property
    def all_cors_origins(self) -> List[str]:
        """Merge CORS_ORIGINS with any Railway public URLs."""
        origins = self.cors_origins_list

        for domain in [self.RAILWAY_PUBLIC_DOMAIN, self.RAILWAY_STATIC_URL]:
            if domain:
                url = f"https://{domain}" if not domain.startswith("http") else domain
                if url not in origins:
                    origins.append(url)

        if self.FRONTEND_URL and "localhost" not in self.FRONTEND_URL:
            if self.FRONTEND_URL not in origins:
                origins.append(self.FRONTEND_URL)

        return origins

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
