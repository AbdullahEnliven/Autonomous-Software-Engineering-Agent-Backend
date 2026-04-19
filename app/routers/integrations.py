from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
from app.config import settings

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.integration import (
    DeployRequest,
    DeployResponse,
    GithubConnectRequest,
    GithubConnectResponse,
    GithubOAuthUrlResponse,
    GithubOrgsResponse,
    GithubPushRequest,
    GithubPushResponse,
    GithubStatusResponse,
    SupabaseConnectionResponse,
    SupabaseCredentials,
    SupabaseMigrationResponse,
    SupabaseStatusResponse,
    VercelStatusResponse,
)
from app.services.integration_service import IntegrationService
from app.services.deployment_service import DeploymentService

router = APIRouter()


@router.get("/github/oauth-url", response_model=GithubOAuthUrlResponse)
async def get_github_oauth_url(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await IntegrationService.get_github_oauth_url(db, project_id, str(current_user.id))


@router.post("/github/connect", response_model=GithubConnectResponse)
async def connect_github(
    project_id: str,
    payload: GithubConnectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await IntegrationService.connect_github(
        db,
        project_id,
        str(current_user.id),
        payload.code,
        payload.state,
    )


@router.get("/github/status", response_model=GithubStatusResponse)
async def get_github_status(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await IntegrationService.get_github_status(db, project_id, str(current_user.id))


@router.get("/github/orgs", response_model=GithubOrgsResponse)
async def get_github_orgs(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await IntegrationService.get_github_orgs(db, project_id, str(current_user.id))


@router.post("/github/push", response_model=GithubPushResponse)
async def push_to_github(
    project_id: str,
    payload: GithubPushRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await IntegrationService.push_to_github(
        db,
        project_id,
        str(current_user.id),
        repo_name=payload.repoName.strip(),
        is_private=payload.isPrivate,
        branch=payload.branch.strip(),
        commit_message=payload.commitMessage.strip(),
        owner=payload.owner.strip() if payload.owner else None,
    )


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


@router.get("/supabase/init-script", status_code=status.HTTP_200_OK)
async def get_supabase_init_script(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate project access first.
    await IntegrationService.get_supabase_status(db, project_id, current_user.id)

    backend_dir = Path(__file__).resolve().parents[2]
    root_dir = backend_dir.parent
    script_path = root_dir / "supabasescript.txt"

    if not script_path.exists():
        raise HTTPException(status_code=404, detail="Supabase init script not found")

    return {"script": script_path.read_text(encoding="utf-8")}


@router.post(
    "/deploy",
    response_model=DeployResponse,
    status_code=status.HTTP_200_OK,
)
async def deploy_project(
    project_id: str,
    payload: DeployRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deploy project (Vercel when configured, legacy fallback otherwise)."""
    try:
        pid_str = str(project_id)
        subdomain = payload.subdomain or f"store-{pid_str[:5]}"
        target = payload.target or "production"

        url = await DeploymentService.deploy_project_for_user(
            db=db,
            project_id=project_id,
            user_id=str(current_user.id),
            subdomain=subdomain,
            target=target,
        )
        return {
            "status": "success",
            "message": f"{target.capitalize()} deploy successful",
            "url": url,
            "target": target,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vercel/status", response_model=VercelStatusResponse)
async def get_vercel_status(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    configured = bool(settings.VERCEL_TOKEN)
    return await IntegrationService.get_vercel_status(db, project_id, str(current_user.id), configured)


@router.post(
    "/vercel/preview",
    response_model=DeployResponse,
    status_code=status.HTTP_200_OK,
)
async def deploy_preview_to_vercel(
    project_id: str,
    payload: DeployRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not settings.VERCEL_TOKEN:
        raise HTTPException(status_code=400, detail="VERCEL_TOKEN is not configured")

    pid_str = str(project_id)
    subdomain = payload.subdomain or f"store-{pid_str[:5]}"
    url = await DeploymentService.deploy_project_for_user(
        db=db,
        project_id=project_id,
        user_id=str(current_user.id),
        subdomain=subdomain,
        target="preview",
    )
    return {
        "status": "success",
        "message": "Preview deploy successful",
        "url": url,
        "target": "preview",
    }


@router.post(
    "/vercel/deploy",
    response_model=DeployResponse,
    status_code=status.HTTP_200_OK,
)
async def deploy_production_to_vercel(
    project_id: str,
    payload: DeployRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not settings.VERCEL_TOKEN:
        raise HTTPException(status_code=400, detail="VERCEL_TOKEN is not configured")

    pid_str = str(project_id)
    subdomain = payload.subdomain or f"store-{pid_str[:5]}"
    url = await DeploymentService.deploy_project_for_user(
        db=db,
        project_id=project_id,
        user_id=str(current_user.id),
        subdomain=subdomain,
        target="production",
    )
    return {
        "status": "success",
        "message": "Production deploy successful",
        "url": url,
        "target": "production",
    }
