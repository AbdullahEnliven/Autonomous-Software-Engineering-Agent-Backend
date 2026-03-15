from pydantic import BaseModel, HttpUrl
from typing import Optional, List
from datetime import datetime
import uuid
from app.models.project import ProjectStatus

class ProjectCreate(BaseModel):
    storeName: Optional[str] = None
    requirements: str
    category: Optional[str] = None
    targetMarket: Optional[str] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[ProjectStatus] = None
    thumbnail_url: Optional[str] = None

class ProjectResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    slug: str
    status: ProjectStatus
    thumbnail_url: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class ProjectStats(BaseModel):
    total_files: int
    generation_progress: int
    downloads: int
