from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.dependencies import get_current_user
from app.schemas.specification import SpecificationGenerateRequest, SpecificationUpdate, SpecificationResponse
from app.services.specification_service import SpecificationService

router = APIRouter()

@router.post("/generate", response_model=SpecificationResponse, status_code=status.HTTP_201_CREATED)
async def generate_specification(
    project_id: str,
    req: SpecificationGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Trigger Gemini spec generation from requirement."""
    return await SpecificationService.generate_specification(db, req.requirement_id, project_id, current_user.id)

@router.get("/{spec_id}", response_model=SpecificationResponse)
async def get_specification(
    project_id: str,
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get generated specification."""
    return await SpecificationService.get_specification(db, spec_id, project_id, current_user.id)

@router.patch("/{spec_id}", response_model=SpecificationResponse)
async def update_specification(
    project_id: str,
    spec_id: str,
    spec_in: SpecificationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update specification (user edits)."""
    return await SpecificationService.update_specification(db, spec_id, spec_in, project_id, current_user.id)

@router.post("/{spec_id}/confirm", response_model=SpecificationResponse)
async def confirm_specification(
    project_id: str,
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark specification as confirmed (ready for generation)."""
    spec_in = SpecificationUpdate(is_confirmed=True)
    return await SpecificationService.update_specification(db, spec_id, spec_in, project_id, current_user.id)
