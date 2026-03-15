from fastapi import APIRouter, Depends
from app.schemas.auth import UserResponse
from app.models.user import User
from app.dependencies import get_current_user

router = APIRouter()

@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_user)):
    """Get the current authenticated user's profile."""
    return current_user
