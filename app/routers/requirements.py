from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.database import get_db
from app.models.user import User
from app.dependencies import get_current_user
from app.schemas.requirement import RequirementCreate, RequirementUpdate, RequirementResponse
from app.services.requirement_service import RequirementService

router = APIRouter()

@router.get("/", response_model=List[RequirementResponse])
async def list_requirements(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all requirements for a specific project."""
    return await RequirementService.get_requirements(db, project_id, current_user.id)

@router.post("/", response_model=RequirementResponse, status_code=status.HTTP_201_CREATED)
async def submit_requirement(
    project_id: str,
    requirement_in: RequirementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Submit new store requirements for a project."""
    return await RequirementService.create_requirement(db, requirement_in, project_id, current_user.id)

@router.patch("/{requirement_id}", response_model=RequirementResponse)
async def update_requirement(
    project_id: str,
    requirement_id: str,
    requirement_in: RequirementUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update an existing requirement."""
    return await RequirementService.update_requirement(db, requirement_id, requirement_in, project_id, current_user.id)
