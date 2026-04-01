from fastapi import APIRouter, Depends, status, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

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
from app.services.deployment_service import DeploymentService

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


@router.post(
    "/deploy",
    status_code=status.HTTP_200_OK,
)
async def deploy_project(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger the ASEA Cloud deployment sequence."""
    try:
        body_bytes = await request.body()
        body = await request.json() if body_bytes else {}
        pid_str = str(project_id)
        subdomain = body.get("subdomain", f"store-{pid_str[:5]}")
        url = await DeploymentService.deploy_project(project_id, subdomain)
        return {"status": "success", "message": "Deployed successfully", "url": url}
    except Exception as e:
        import traceback
        traceback.print_exc()
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))
