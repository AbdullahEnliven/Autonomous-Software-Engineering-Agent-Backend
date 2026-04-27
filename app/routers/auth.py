from fastapi import APIRouter, Depends, Response, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import OAuth2PasswordRequestForm

from app.database import get_db
from app.schemas.auth import (
    UserCreate,
    UserResponse,
    Token,
    UserLogin,
    GithubOAuthUrlResponse,
    GithubOAuthCallbackRequest,
    ChangePasswordRequest,
)
from app.services.auth_service import AuthService
from app.dependencies import get_current_user
from app.models.user import User
from app.utils.security import get_password_hash, verify_password

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


@router.get("/oauth/github/url", response_model=GithubOAuthUrlResponse)
async def github_oauth_url(source: str = Query(default="login", pattern="^(login|register)$")):
    """Get GitHub OAuth authorize URL for auth login/signup."""
    return await AuthService.get_github_oauth_url(source)


@router.post("/oauth/github")
async def github_oauth_callback(
    payload: GithubOAuthCallbackRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Exchange GitHub OAuth code and authenticate (login/signup)."""
    user, access_token, refresh_token = await AuthService.authenticate_with_github_code(
        db,
        payload.code,
        payload.state,
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=30 * 24 * 60 * 60,
    )

    return {
        "user": user,
        "token": access_token,
    }


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.currentPassword, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    current_user.hashed_password = get_password_hash(payload.newPassword)
    await db.commit()
    return {"message": "Password changed successfully"}


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.delete(current_user)
    await db.commit()
    return None
