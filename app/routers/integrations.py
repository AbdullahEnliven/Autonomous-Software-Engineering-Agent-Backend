from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.integration import (
    SupabaseConnectionResponse,
    SupabaseCredentials,
    SupabaseMigrationResponse,
    SupabaseStatusResponse,
)
from app.services.integration_service import IntegrationService

router = APIRouter()


@router.get("/supabase/status", response_model=SupabaseStatusResponse)
async def get_supabase_status(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await IntegrationService.get_supabase_status(db, project_id, current_user.id)


@router.post(
    "/supabase/test",
    response_model=SupabaseConnectionResponse,
    status_code=status.HTTP_200_OK,
)
async def test_supabase_connection(
    project_id: str,
    credentials: SupabaseCredentials,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await IntegrationService.test_supabase_connection(db, project_id, current_user.id, credentials)


@router.post(
    "/supabase/migrate",
    response_model=SupabaseMigrationResponse,
    status_code=status.HTTP_200_OK,
)
async def run_supabase_migrations(
    project_id: str,
    credentials: SupabaseCredentials,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await IntegrationService.run_supabase_migrations(db, project_id, current_user.id, credentials)


@router.post(
    "/supabase/seed",
    response_model=SupabaseMigrationResponse,
    status_code=status.HTTP_200_OK,
)
async def run_supabase_seed(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await IntegrationService.run_supabase_seed(db, project_id, current_user.id)
