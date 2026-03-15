from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid

class RequirementCreate(BaseModel):
    raw_text: str
    category: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None

class RequirementUpdate(BaseModel):
    raw_text: Optional[str] = None
    enhanced_text: Optional[str] = None
    category: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None

class RequirementResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    raw_text: str
    enhanced_text: Optional[str]
    category: Optional[str]
    preferences: Optional[Dict[str, Any]]
    created_at: datetime
    
    class Config:
        from_attributes = True
