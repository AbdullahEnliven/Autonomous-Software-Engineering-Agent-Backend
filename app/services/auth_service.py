from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta, timezone
import secrets

import httpx
from jose import jwt, JWTError

from app.models.user import User
from app.schemas.auth import UserCreate, UserLogin, Token
from app.utils.security import get_password_hash, verify_password, create_access_token, create_refresh_token
from app.config import settings

class AuthService:
    @staticmethod
    def _encode_github_oauth_state(source: str) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "src": source,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
            "nonce": secrets.token_urlsafe(16),
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

    @staticmethod
    def _decode_github_oauth_state(state: str) -> dict:
        try:
            payload = jwt.decode(state, settings.SECRET_KEY, algorithms=["HS256"])
            if not isinstance(payload, dict):
                raise ValueError("Invalid state payload")
            return payload
        except (JWTError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired GitHub OAuth state",
            ) from exc

    @staticmethod
    def _normalize_email(email: str) -> str:
        return (email or "").strip().lower()

    @staticmethod
    async def get_github_oauth_url(source: str = "login") -> dict:
        if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GitHub OAuth is not configured",
            )

        normalized_source = "register" if source == "register" else "login"
        state = AuthService._encode_github_oauth_state(normalized_source)

        params = {
            "client_id": settings.GITHUB_CLIENT_ID,
            "redirect_uri": settings.GITHUB_REDIRECT_URI,
            "scope": "read:user user:email",
            "state": state,
            "allow_signup": "true",
        }
        auth_url = httpx.URL("https://github.com/login/oauth/authorize", params=params)
        return {"auth_url": str(auth_url), "state": state}

    @staticmethod
    async def authenticate_with_github_code(db: AsyncSession, code: str, state: str) -> tuple[User, str, str]:
        AuthService._decode_github_oauth_state(state)

        token_payload = {
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.GITHUB_REDIRECT_URI,
            "state": state,
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                token_res = await client.post(
                    "https://github.com/login/oauth/access_token",
                    json=token_payload,
                    headers={"Accept": "application/json"},
                )
                token_res.raise_for_status()
                token_data = token_res.json()
                access_token = token_data.get("access_token")
                if not access_token:
                    detail = token_data.get("error_description") or "Failed to retrieve access token"
                    raise HTTPException(status_code=400, detail=detail)

                user_res = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                user_res.raise_for_status()
                gh_user = user_res.json()

                email = gh_user.get("email")
                if not email:
                    emails_res = await client.get(
                        "https://api.github.com/user/emails",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Accept": "application/vnd.github+json",
                            "X-GitHub-Api-Version": "2022-11-28",
                        },
                    )
                    emails_res.raise_for_status()
                    emails = emails_res.json() or []
                    primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
                    fallback = next((e for e in emails if e.get("verified")), None)
                    selected = primary or fallback
                    email = selected.get("email") if selected else None
        except HTTPException:
            raise
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"GitHub OAuth failed: {exc}",
            ) from exc

        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GitHub account does not expose a verified email",
            )

        normalized_email = AuthService._normalize_email(email)
        result = await db.execute(select(User).where(User.email == normalized_email))
        user = result.scalars().first()

        if user is None:
            gh_name = gh_user.get("name") or gh_user.get("login") or normalized_email.split("@")[0]
            generated_password = secrets.token_urlsafe(24)
            user = User(
                email=normalized_email,
                hashed_password=get_password_hash(generated_password),
                full_name=gh_name,
                avatar_url=gh_user.get("avatar_url"),
                is_verified=True,
            )
            db.add(user)
            try:
                await db.commit()
                await db.refresh(user)
            except IntegrityError:
                await db.rollback()
                result = await db.execute(select(User).where(User.email == normalized_email))
                user = result.scalars().first()
                if user is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Could not complete GitHub signup",
                    )
        else:
            user.avatar_url = user.avatar_url or gh_user.get("avatar_url")
            user.full_name = user.full_name or gh_user.get("name") or gh_user.get("login")
            user.is_verified = True
            await db.commit()

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inactive user",
            )

        local_access_token = create_access_token(subject=user.id)
        refresh_token = create_refresh_token(subject=user.id)
        return user, local_access_token, refresh_token
    
    @staticmethod
    async def register_user(db: AsyncSession, user_in: UserCreate) -> User:
        normalized_email = AuthService._normalize_email(user_in.email)
        result = await db.execute(select(User).where(User.email == normalized_email))
        if result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
            
        hashed_password = get_password_hash(user_in.password)
        db_user = User(
            email=normalized_email,
            hashed_password=hashed_password,
            full_name=user_in.full_name
        )
        
        db.add(db_user)
        try:
            await db.commit()
            await db.refresh(db_user)
            return db_user
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not register user"
            )

    @staticmethod
    async def authenticate_user(db: AsyncSession, user_in: UserLogin) -> tuple[str, str]:
        normalized_email = AuthService._normalize_email(user_in.email)
        result = await db.execute(select(User).where(User.email == normalized_email))
        user = result.scalars().first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        password_ok = verify_password(user_in.password, user.hashed_password)

        # Legacy compatibility: if an old row stored plaintext password, allow one-time login
        # and immediately upgrade to bcrypt hash.
        if not password_ok and user.hashed_password == user_in.password:
            user.hashed_password = get_password_hash(user_in.password)
            await db.commit()
            password_ok = True

        if not password_ok:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inactive user"
            )
            
        access_token = create_access_token(subject=user.id)
        refresh_token = create_refresh_token(subject=user.id)
        
        return access_token, refresh_token
