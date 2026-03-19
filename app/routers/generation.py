from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.database import get_db
from app.models.user import User
from app.dependencies import get_current_user
from app.services.generation_service import GenerationService

router = APIRouter()

@router.get("/{job_id}/status")
async def get_generation_status(
    project_id: str,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    job = await GenerationService.get_job(db, job_id, project_id, current_user.id)
    return {
        "id": str(job.id),
        "status": job.status.value if hasattr(job.status, 'value') else job.status,
        "progress": job.progress,
        "current_step": job.current_step
    }
