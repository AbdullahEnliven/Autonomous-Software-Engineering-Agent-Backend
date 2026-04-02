from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from pathlib import Path
import hashlib
import tempfile
import zipfile

from app.database import get_db
from app.models.user import User
from app.models.project import Specification, GenerationJobStatus
from app.dependencies import get_current_user
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse
from app.schemas.requirement import RequirementCreate
from app.services.project_service import ProjectService
from app.services.requirement_service import RequirementService
from app.services.specification_service import SpecificationService
from app.services.generation_service import GenerationService
from app.services.chat_service import ChatService
from app.services.version_control_service import VersionControlService
from app.services.name_selector_service import NameSelectorService
from app.utils.paths import get_project_dir
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

@router.get("/", response_model=List[ProjectResponse])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all projects for the current user."""
    return await ProjectService.get_projects(db, current_user.id)

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
    return {
        "status": "ok",
        "restored_checkpoint": {
            "id": str(checkpoint.id),
            "message": checkpoint.message,
            "commit_hash": checkpoint.commit_hash,
            "created_at": checkpoint.created_at,
        },
    }

@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get project details."""
    return await ProjectService.get_project(db, project_id, current_user.id)

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

@router.get("/{project_id}/preview/{page}")
async def get_project_preview(project_id: str, page: str, current_user: User = Depends(get_current_user)):
    """Return specific preview HTML based on stable generated port."""
    # Deterministic port based on Project ID
    base_hash = int(hashlib.md5(str(project_id).encode()).hexdigest(), 16)
    port = 6000 + (base_hash % 3000)
    
    return f"""<style>body {{ margin: 0; padding: 0; overflow: hidden; }} iframe {{ width: 100vw; height: 100vh; border: none; }}</style><iframe src="http://localhost:{port}/{"" if page == "home" else page.lower()}"></iframe>"""


