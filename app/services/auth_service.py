from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError

from app.models.user import User
from app.schemas.auth import UserCreate, UserLogin, Token
from app.utils.security import get_password_hash, verify_password, create_access_token, create_refresh_token

class AuthService:
    @staticmethod
    def _normalize_email(email: str) -> str:
        return (email or "").strip().lower()
    
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
