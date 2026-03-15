from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

from app.models.project import GenerationJobStatus

class GenerationJobCreate(BaseModel):
    specification_id: str

class GenerationJobResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    specification_id: uuid.UUID
    celery_task_id: Optional[str]
    status: GenerationJobStatus
    progress: int
    current_step: Optional[str]
    logs: List[Dict[str, Any]]
    error_message: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True
