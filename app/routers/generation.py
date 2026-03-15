from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.dependencies import get_current_user
from app.schemas.generation import GenerationJobCreate, GenerationJobResponse
from app.services.generation_service import GenerationService

router = APIRouter()

@router.post("/start", response_model=GenerationJobResponse, status_code=status.HTTP_201_CREATED)
async def start_generation(
    project_id: str,
    req: GenerationJobCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Start generation Celery job."""
    return await GenerationService.start_generation(db, project_id, req.specification_id, current_user.id)

@router.get("/{job_id}/status", response_model=GenerationJobResponse)
async def get_generation_status(
    project_id: str,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get current job status and progress."""
    return await GenerationService.get_job(db, job_id, project_id, current_user.id)
