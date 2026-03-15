from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid

class SpecificationGenerateRequest(BaseModel):
    requirement_id: str

class SpecificationUpdate(BaseModel):
    store_name: Optional[str] = None
    tagline: Optional[str] = None
    modules: Optional[List[str]] = None
    data_models: Optional[Dict[str, Any]] = None
    pages: Optional[List[str]] = None
    features: Optional[Dict[str, Any]] = None
    api_structure: Optional[Dict[str, Any]] = None
    is_confirmed: Optional[bool] = None

class SpecificationResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    requirement_id: uuid.UUID
    store_name: str
    tagline: Optional[str]
    modules: List[str]
    data_models: Dict[str, Any]
    pages: List[str]
    features: Dict[str, Any]
    api_structure: Dict[str, Any]
    is_confirmed: bool
    created_at: datetime
    
    class Config:
        from_attributes = True
