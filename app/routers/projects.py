from fastapi import APIRouter, Depends, status, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from pathlib import Path
import hashlib
import httpx
import json
import tempfile
import zipfile
import time

from app.database import get_db, async_session_maker
from app.models.user import User
from app.models.project import Specification, GenerationJobStatus, Integration, IntegrationType
from app.dependencies import get_current_user
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse
from app.schemas.requirement import RequirementCreate
from app.services.project_service import ProjectService
from app.services.requirement_service import RequirementService
from app.services.specification_service import SpecificationService
from app.services.generation_service import GenerationService
from app.services.chat_service import ChatService
from app.services.version_control_service import VersionControlService
from app.services.integration_service import IntegrationService
from app.services.name_selector_service import NameSelectorService
from app.services.preview_manager import PreviewManager
from app.services.deployment_service import DeploymentService
from app.utils.paths import get_project_dir
from app.config import settings
from app.socketio.server import sio
from pydantic import BaseModel
from sqlalchemy.future import select

router = APIRouter()

class EnhanceRequest(BaseModel):
    text: str


class CheckpointCreateRequest(BaseModel):
    message: str = ""


class FileUpdateRequest(BaseModel):
    content: str


IGNORED_DIRS = {".git", "node_modules", "dist", "build", "__pycache__", ".pytest_cache"}


def _get_project_dir(project_id: str) -> Path:
    return get_project_dir(project_id)


def _safe_project_path(project_id: str, file_path: str) -> Path:
    project_dir = _get_project_dir(project_id).resolve()
    rel = (file_path or "").replace("\\", "/").lstrip("/")
    candidate = (project_dir / rel).resolve()
    if project_dir not in candidate.parents and candidate != project_dir:
        raise HTTPException(status_code=400, detail="Invalid file path")
    return candidate

@router.get("", response_model=List[ProjectResponse])
@router.get("/", response_model=List[ProjectResponse])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all projects for the current user."""
    return await ProjectService.get_projects(db, current_user.id)

@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new project, submit requirement, and generate spec in one go."""
    # 1. Resolve project/store name.
    provided_name = (project_in.storeName or "").strip()
    if provided_name:
        project_name = provided_name
        name_source = "user"
    else:
        project_name = NameSelectorService.select_name_with_groq(
            requirements=project_in.requirements,
            category=project_in.category,
            target_market=project_in.targetMarket,
        )
        name_source = "groq"

    # 2. Create project
    project_create_schema = ProjectCreate(
        storeName=project_name, 
        requirements=project_in.requirements,
        category=project_in.category,
        targetMarket=project_in.targetMarket
    )
    # Patch for old create
    project = await ProjectService.create_project(db, project_create_schema, current_user.id)
    
    # 3. Create requirement
    req_in = RequirementCreate(
        raw_text=project_in.requirements,
        category=project_in.category,
        preferences={
            **({"targetMarket": project_in.targetMarket} if project_in.targetMarket else {}),
            "explicit_store_name": project_name,
            "store_name_source": name_source,
        }
    )
    req = await RequirementService.create_requirement(db, req_in, str(project.id), current_user.id)

    # Seed chat history so the first chat message is the original store description.
    if project_in.requirements and project_in.requirements.strip():
        try:
            await ChatService.create_message(
                db,
                str(project.id),
                "user",
                project_in.requirements.strip(),
                {"source": "project_creation"},
            )
        except Exception:
            # If migrations are not applied yet, do not block project creation.
            pass
    
    # 4. Generate spec
    spec = await SpecificationService.generate_specification(
        db,
        str(req.id),
        str(project.id),
        current_user.id,
        forced_store_name=project_name,
    )
    
    return {
        "project": project,
        "spec": spec
    }


@router.get("/{project_id}/chat-history")
async def get_project_chat_history(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await ProjectService.get_project(db, project_id, current_user.id)
    messages = await ChatService.get_messages(db, project_id)
    return {
        "messages": [
            {
                "id": str(message.id),
                "role": message.role,
                "content": message.content,
                "metadata": message.message_metadata or {},
                "created_at": message.created_at,
            }
            for message in messages
        ]
    }


@router.get("/{project_id}/checkpoints")
async def list_project_checkpoints(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await ProjectService.get_project(db, project_id, current_user.id)
    checkpoints = await VersionControlService.list_checkpoints(db, project_id)
    return {
        "checkpoints": [
            {
                "id": str(checkpoint.id),
                "message": checkpoint.message,
                "commit_hash": checkpoint.commit_hash,
                "created_at": checkpoint.created_at,
            }
            for checkpoint in checkpoints
        ]
    }


@router.post("/{project_id}/checkpoints", status_code=status.HTTP_201_CREATED)
async def create_project_checkpoint(
    project_id: str,
    payload: CheckpointCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await ProjectService.get_project(db, project_id, current_user.id)
    checkpoint = await VersionControlService.create_checkpoint(db, project_id, payload.message)
    return {
        "checkpoint": {
            "id": str(checkpoint.id),
            "message": checkpoint.message,
            "commit_hash": checkpoint.commit_hash,
            "created_at": checkpoint.created_at,
        }
    }


@router.post("/{project_id}/checkpoints/{checkpoint_id}/restore")
async def restore_project_checkpoint(
    project_id: str,
    checkpoint_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await ProjectService.get_project(db, project_id, current_user.id)
    checkpoint = await VersionControlService.restore_checkpoint(db, project_id, checkpoint_id)
    await PreviewManager.restart_preview(project_id)

    github_push = {"pushed": False, "reason": "repo_not_configured"}
    try:
        github_push = await IntegrationService.auto_push_connected_repo(db, project_id, str(current_user.id))
    except HTTPException as exc:
        github_push = {"pushed": False, "error": str(exc.detail)}

    return {
        "status": "ok",
        "restored_checkpoint": {
            "id": str(checkpoint.id),
            "message": checkpoint.message,
            "commit_hash": checkpoint.commit_hash,
            "created_at": checkpoint.created_at,
        },
        "github_push": github_push,
    }

@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get project details."""
    return await ProjectService.get_project_response(db, project_id, current_user.id)

@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    project_in: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update project details."""
    return await ProjectService.update_project(db, project_id, current_user.id, project_in)

@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a project."""
    await ProjectService.delete_project(db, project_id, current_user.id)
    return None

@router.get("/{project_id}/spec")
async def get_project_spec(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    await ProjectService.get_project(db, project_id, current_user.id)
    result = await db.execute(select(Specification).where(Specification.project_id == project_id).order_by(Specification.created_at.desc()))
    spec = result.scalars().first()
    if not spec:
        raise HTTPException(status_code=404, detail="Spec not found")
    return spec

@router.post("/{project_id}/generate")
async def start_generation_wrapper(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Get latest spec
    result = await db.execute(select(Specification).where(Specification.project_id == project_id).order_by(Specification.created_at.desc()))
    spec = result.scalars().first()
    if not spec:
        raise HTTPException(status_code=404, detail="Spec not found")
        
    # Mark as confirmed implicitly if frontend doesn't do it
    spec.is_confirmed = True
    await db.commit()
    
    return await GenerationService.start_generation(db, project_id, str(spec.id), current_user.id)

@router.post("/enhance-requirements")
async def enhance_requirements(req: EnhanceRequest, current_user: User = Depends(get_current_user)):
    """Mock endpoint to enhance requirements using AI."""
    enhanced = f"Enhanced requirement based on: {req.text}. We will build a comprehensive e-commerce platform with all necessary modules including auth, payment, and product management."
    return {"enhanced": enhanced}

@router.get("/{project_id}/files")
async def get_project_files(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return recursive project files for the code viewer."""
    await ProjectService.get_project(db, project_id, current_user.id)

    project_dir = _get_project_dir(project_id)
    if not project_dir.exists() or not project_dir.is_dir():
        raise HTTPException(status_code=404, detail="Project files not found")

    files = []
    for path in project_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(project_dir).as_posix()
        parts = rel.split("/")
        if any(part in IGNORED_DIRS for part in parts):
            continue
        files.append(
            {
                "id": rel,
                "name": path.name,
                "type": "file",
                "path": rel,
                "size": path.stat().st_size,
            }
        )

    files.sort(key=lambda item: item["path"])
    return {"files": files}


@router.get("/{project_id}/files/{file_path:path}")
async def get_project_file_content(
    project_id: str,
    file_path: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await ProjectService.get_project(db, project_id, current_user.id)

    path = _safe_project_path(project_id, file_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Binary files are not supported in editor")

    return {"path": path.relative_to(_get_project_dir(project_id)).as_posix(), "content": content}


@router.patch("/{project_id}/files/{file_path:path}")
async def update_project_file_content(
    project_id: str,
    file_path: str,
    payload: FileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await ProjectService.get_project(db, project_id, current_user.id)

    path = _safe_project_path(project_id, file_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        path.write_text(payload.content, encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update file: {exc}")

    return {"status": "ok", "path": path.relative_to(_get_project_dir(project_id)).as_posix()}


@router.get("/{project_id}/download")
async def download_project_zip(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download project source as a zip (excluding heavy runtime folders)."""
    await ProjectService.get_project(db, project_id, current_user.id)

    project_dir = _get_project_dir(project_id)
    if not project_dir.exists() or not project_dir.is_dir():
        raise HTTPException(status_code=404, detail="Project files not found")

    tmp_dir = Path(tempfile.mkdtemp(prefix="asea_zip_"))
    zip_path = tmp_dir / f"project-{project_id}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in project_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(project_dir).as_posix()
            parts = rel.split("/")
            if any(part in IGNORED_DIRS for part in parts):
                continue
            zf.write(path, arcname=rel)

    return FileResponse(
        path=str(zip_path),
        filename=f"project-{project_id}.zip",
        media_type="application/zip",
    )

# ---------------------------------------------------------------------------
# Preview endpoints (Vercel-based)
# ---------------------------------------------------------------------------

@router.get("/{project_id}/preview-status")
async def get_preview_status(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns current preview state:
      { status: idle|deploying|ready|error, url: str|null, message: str }
    Does NOT trigger a deploy — call POST /preview/trigger for that.
    """
    await ProjectService.get_project(db, project_id, current_user.id)

    # Read DB integration for all stored URLs
    result = await db.execute(
        select(Integration).where(
            Integration.project_id == project_id,
            Integration.type == IntegrationType.vercel,
        )
    )
    integration = result.scalars().first()
    stored_url: Optional[str] = None
    stored_hash: Optional[str] = None
    production_url: Optional[str] = None
    if integration and integration.encrypted_credentials:
        try:
            creds = json.loads(integration.encrypted_credentials)
            stored_url = creds.get("preview_url")
            stored_hash = creds.get("preview_file_hash")
            production_url = creds.get("production_url")
        except Exception:
            pass

    mem_status = PreviewManager.get_status(project_id)

    # If in-memory says ready, trust it — enrich with production_url
    if mem_status["status"] == "ready" and mem_status["url"]:
        return JSONResponse({**mem_status, "production_url": production_url})

    # If DB has a URL, return it as ready (memory was cleared by restart)
    if stored_url:
        return JSONResponse({
            "status": "ready",
            "url": stored_url,
            "message": "Preview ready",
            "file_hash": stored_hash,
            "production_url": production_url,
        })

    return JSONResponse({**mem_status, "production_url": production_url})


@router.get("/{project_id}/preview-proxy")
async def preview_proxy(
    project_id: str,
    token: str,                         # JWT passed as ?token= since iframes can't send headers
    db: AsyncSession = Depends(get_db),
):
    """
    Transparent reverse-proxy for the Vercel preview page.
    Fetches the page server-side and strips X-Frame-Options / CSP headers
    so the frontend can embed it in an iframe without 'refused to connect'.
    Token is accepted as a query parameter (iframes cannot set Authorization headers).
    """
    from jose import jwt, JWTError
    from app.config import settings
    from app.utils.security import ALGORITHM

    # Validate token manually (same logic as get_current_user)
    credentials_exc = HTTPException(status_code=401, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    result_user = await db.execute(select(User).where(User.id == user_id))
    current_user = result_user.scalars().first()
    if not current_user or not current_user.is_active:
        raise credentials_exc

    # Verify the user owns this project
    await ProjectService.get_project(db, project_id, current_user.id)

    # Look up the current preview URL (in-memory first, then DB)
    from app.services.preview_manager import PreviewManager
    mem = PreviewManager.get_status(project_id)
    preview_url: Optional[str] = mem.get("url") if mem.get("status") == "ready" else None

    if not preview_url:
        result_int = await db.execute(
            select(Integration).where(
                Integration.project_id == project_id,
                Integration.type == IntegrationType.vercel,
            )
        )
        integration = result_int.scalars().first()
        if integration and integration.encrypted_credentials:
            try:
                creds = json.loads(integration.encrypted_credentials)
                preview_url = creds.get("preview_url")
            except Exception:
                pass

    if not preview_url:
        raise HTTPException(status_code=404, detail="No preview URL available. Trigger a preview build first.")

    # Fetch the Vercel page server-side
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            resp = await client.get(preview_url, headers={"User-Agent": "ASEA-PreviewProxy/1.0"})
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach preview URL: {exc}")

    # Strip headers that block iframe embedding
    STRIP = {"x-frame-options", "content-security-policy", "x-content-type-options",
             "transfer-encoding", "connection", "content-encoding", "content-length"}
    safe_headers = {k: v for k, v in resp.headers.items() if k.lower() not in STRIP}
    safe_headers["X-Frame-Options"] = "ALLOWALL"
    safe_headers["Access-Control-Allow-Origin"] = "*"

    content_type = resp.headers.get("content-type", "text/html; charset=utf-8")
    content = resp.content

    # Inject <base href="..."> for HTML responses so relative SPA assets load from Vercel
    if b"text/html" in content_type.lower().encode():
        base_tag = f'<base href="{preview_url}/">\n'.encode("utf-8")
        if b"<head>" in content:
            content = content.replace(b"<head>", b"<head>\n" + base_tag, 1)
        else:
            content = base_tag + content

    return Response(
        content=content,
        status_code=resp.status_code,
        headers=safe_headers,
        media_type=content_type,
    )


@router.post("/{project_id}/preview/trigger")
async def trigger_preview_deploy(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Triggers a Vercel preview deploy (non-blocking).
    Returns immediately with current status; frontend polls /preview-status
    or listens for the `preview_status` Socket.IO event.
    """
    await ProjectService.get_project(db, project_id, current_user.id)

    if not settings.VERCEL_TOKEN:
        raise HTTPException(
            status_code=400,
            detail="VERCEL_TOKEN is not configured. Cannot deploy preview.",
        )

    # Get stored state from DB
    result = await db.execute(
        select(Integration).where(
            Integration.project_id == project_id,
            Integration.type == IntegrationType.vercel,
        )
    )
    integration = result.scalars().first()
    stored_url: Optional[str] = None
    stored_hash: Optional[str] = None
    project_slug: str = f"{settings.VERCEL_PROJECT_PREFIX}-{str(project_id)[:8]}".lower()
    if integration and integration.encrypted_credentials:
        try:
            creds = json.loads(integration.encrypted_credentials)
            stored_url = creds.get("preview_url")
            stored_hash = creds.get("preview_file_hash")
            project_slug = creds.get("project_slug") or project_slug
        except Exception:
            pass

    # Open a new DB session for the background task (the current `db` session
    # belongs to this request and will be closed when it ends).
    async with async_session_maker() as bg_db:
        result_dict = await PreviewManager.get_or_create_preview(
            project_id=project_id,
            vercel_token=settings.VERCEL_TOKEN,
            vercel_scope=settings.VERCEL_SCOPE,
            project_slug=project_slug,
            sio=sio,
            db=bg_db,
            stored_url=stored_url,
            stored_hash=stored_hash,
        )

    return JSONResponse(result_dict)


# Legacy route kept for backward-compat — redirects to the new trigger flow
@router.get("/{project_id}/preview/{page}", response_class=HTMLResponse)
async def get_project_preview_legacy(
    project_id: str,
    page: str,
    current_user: User = Depends(get_current_user),
):
    """Backward-compat stub. Returns a redirect page pointing to Vercel preview."""
    status_dict = PreviewManager.get_status(project_id)
    url = status_dict.get("url")
    if url:
        page_path = "" if page == "home" else page.lower()
        target = f"{url.rstrip('/')}/{page_path}" if page_path else url
        return HTMLResponse(
            content=f"""<style>body{{margin:0;padding:0;overflow:hidden}}
            iframe{{width:100vw;height:100vh;border:none}}</style>
            <iframe src="{target}"></iframe>"""
        )
    return HTMLResponse(
        content="""<html><body style='font-family:sans-serif;display:flex;
        align-items:center;justify-content:center;height:100vh;background:#0f172a;color:#e5e7eb'>
        <div style='text-align:center'><h2>Preview not ready</h2>
        <p>Use the builder to trigger a Vercel preview deploy.</p></div>
        </body></html>"""
    )


