from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
import uuid

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: Optional[str] = None
    company_name: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    primary_goal: Optional[str] = None
    store_stage: Optional[str] = None
    monthly_revenue: Optional[str] = None
    referral_source: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class GithubOAuthUrlResponse(BaseModel):
    auth_url: str
    state: str


class GithubOAuthCallbackRequest(BaseModel):
    code: str
    state: str

class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: Optional[str]
    avatar_url: Optional[str]
    company_name: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    primary_goal: Optional[str] = None
    store_stage: Optional[str] = None
    monthly_revenue: Optional[str] = None
    referral_source: Optional[str] = None
    onboarding_completed: bool = False
    plan: str
    is_active: bool
    is_verified: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    company_name: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    primary_goal: Optional[str] = None
    store_stage: Optional[str] = None
    monthly_revenue: Optional[str] = None
    referral_source: Optional[str] = None
    onboarding_completed: Optional[bool] = None


class ChangePasswordRequest(BaseModel):
    currentPassword: str = Field(min_length=1)
    newPassword: str = Field(min_length=8)
