from fastapi import APIRouter, Depends, Response, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import OAuth2PasswordRequestForm

from app.database import get_db
from app.schemas.auth import UserCreate, UserResponse, Token, UserLogin
from app.services.auth_service import AuthService
from app.dependencies import get_current_user

router = APIRouter()

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user."""
    user = await AuthService.register_user(db, user_in)
    
    # Auto-login after register to return {user, token}
    access_token, refresh_token = await AuthService.authenticate_user(
        db, UserLogin(email=user_in.email, password=user_in.password)
    )
    
    return {
        "user": user,
        "token": access_token
    }

@router.post("/login", response_model=Token)
async def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: AsyncSession = Depends(get_db)
):
    """Email and password login (supports form data for Swagger UI)."""
    user_in = UserLogin(email=form_data.username, password=form_data.password)
    access_token, refresh_token = await AuthService.authenticate_user(db, user_in)
    
    # Store refresh token in HttpOnly cookie
    response.set_cookie(
        key="refresh_token", 
        value=refresh_token, 
        httponly=True, 
        secure=True, 
        samesite="lax",
        max_age=30 * 24 * 60 * 60  # 30 days
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/login/json")
async def login_json(
    user_in: UserLogin, 
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    """Email and password login via JSON body."""
    access_token, refresh_token = await AuthService.authenticate_user(db, user_in)
    
    # Also fetch user to return it
    from sqlalchemy.future import select
    from app.models.user import User
    result = await db.execute(select(User).where(User.email == user_in.email))
    user = result.scalars().first()
    
    response.set_cookie(
        key="refresh_token", 
        value=refresh_token, 
        httponly=True, 
        secure=True, 
        samesite="lax",
        max_age=30 * 24 * 60 * 60
    )
    
    return {
        "user": user,
        "token": access_token
    }

@router.post("/logout")
async def logout(response: Response):
    """Logout by clearing refresh token."""
    response.delete_cookie(key="refresh_token")
    return {"message": "Logged out successfully"}
