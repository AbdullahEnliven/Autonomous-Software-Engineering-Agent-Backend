import json

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import uuid

from app.models.project import Integration, IntegrationStatus, IntegrationType, Project, ProjectStatus
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services.thumbnail_service import ThumbnailService
from app.utils.paths import get_project_dir

class ProjectService:
    IGNORED_STORAGE_DIRS = {".git", "node_modules", "dist", "build", "__pycache__", ".pytest_cache"}

    @staticmethod
    def _project_storage_bytes(project_id: str | uuid.UUID) -> int:
        project_dir = get_project_dir(str(project_id))
        if not project_dir.exists() or not project_dir.is_dir():
            return 0

        total = 0
        for path in project_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(project_dir).as_posix()
            except ValueError:
                continue
            if any(part in ProjectService.IGNORED_STORAGE_DIRS for part in rel.split("/")):
                continue
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    @staticmethod
    def _decode_integration_payload(integration: Integration | None) -> dict:
        if not integration or not integration.encrypted_credentials:
            return {}

        try:
            parsed = json.loads(integration.encrypted_credentials)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _serialize_project(
        project: Project,
        vercel: Integration | None = None,
        supabase: Integration | None = None,
    ) -> dict:
        payload = ProjectService._decode_integration_payload(vercel)

        production_url = payload.get("production_url")
        preview_url = payload.get("preview_url")
        vercel_url = production_url or preview_url
        is_live = (
            vercel is not None
            and vercel.status == IntegrationStatus.connected
            and isinstance(vercel_url, str)
            and bool(vercel_url.strip())
        )
        supabase_connected = (
            supabase is not None
            and supabase.status == IntegrationStatus.connected
        )

        return {
            "id": project.id,
            "user_id": project.user_id,
            "name": project.name,
            "slug": project.slug,
            "status": ProjectStatus.deployed if is_live else project.status,
            "thumbnail_url": project.thumbnail_url,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "storage_bytes": ProjectService._project_storage_bytes(project.id),
            "vercel_url": vercel_url if isinstance(vercel_url, str) else None,
            "vercel_preview_url": preview_url if isinstance(preview_url, str) else None,
            "vercel_production_url": production_url if isinstance(production_url, str) else None,
            "is_live": is_live,
            "supabase_connected": supabase_connected,
        }

    @staticmethod
    async def get_project_response(db: AsyncSession, project_id: str, user_id: str) -> dict:
        project = await ProjectService.get_project(db, project_id, user_id)
        integrations_result = await db.execute(
            select(Integration).where(
                Integration.project_id == project.id,
                Integration.type.in_([IntegrationType.vercel, IntegrationType.supabase]),
            )
        )
        integrations = {
            integration.type: integration
            for integration in integrations_result.scalars().all()
        }
        return ProjectService._serialize_project(
            project,
            integrations.get(IntegrationType.vercel),
            integrations.get(IntegrationType.supabase),
        )

    @staticmethod
    async def get_projects(db: AsyncSession, user_id: str):
        result = await db.execute(
            select(Project)
            .where(Project.user_id == user_id)
            .order_by(Project.created_at.desc())
        )
        projects = result.scalars().all()
        if not projects:
            return []

        project_ids = [project.id for project in projects]
        integrations_result = await db.execute(
            select(Integration).where(
                Integration.project_id.in_(project_ids),
                Integration.type.in_([IntegrationType.vercel, IntegrationType.supabase]),
            )
        )
        integrations_by_project_id = {}
        for integration in integrations_result.scalars().all():
            integrations_by_project_id.setdefault(integration.project_id, {})[integration.type] = integration

        thumbnail_changed = False
        for project in projects:
            thumbnail_changed = ThumbnailService.ensure_thumbnail_url(project) or thumbnail_changed
            if not ThumbnailService.existing_thumbnail_path(str(project.id)):
                ThumbnailService._write_placeholder(project)
        if thumbnail_changed:
            await db.commit()

        return [
            ProjectService._serialize_project(
                project,
                integrations_by_project_id.get(project.id, {}).get(IntegrationType.vercel),
                integrations_by_project_id.get(project.id, {}).get(IntegrationType.supabase),
            )
            for project in projects
        ]

    @staticmethod
    async def get_project(db: AsyncSession, project_id: str, user_id: str) -> Project:
        result = await db.execute(select(Project).where(Project.id == project_id, Project.user_id == user_id))
        project = result.scalars().first()
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        return project

    @staticmethod
    async def create_project(db: AsyncSession, project_in: ProjectCreate, user_id: str) -> Project:
        # Generate a simple slug
        project_name = project_in.storeName or "Untitled Store"
        base_slug = project_name.lower().replace(" ", "-")
        slug = f"{base_slug}-{str(uuid.uuid4())[:8]}"
        
        db_project = Project(
            user_id=user_id,
            name=project_name,
            slug=slug
        )
        db.add(db_project)
        await db.commit()
        await db.refresh(db_project)
        ThumbnailService.ensure_thumbnail_url(db_project)
        ThumbnailService._write_placeholder(db_project)
        await db.commit()
        await db.refresh(db_project)
        return db_project

    @staticmethod
    async def generate_project_thumbnails(db: AsyncSession, user_id: str):
        result = await db.execute(
            select(Project)
            .where(Project.user_id == user_id)
            .order_by(Project.created_at.desc())
        )
        projects = result.scalars().all()
        if not projects:
            return []

        project_ids = [project.id for project in projects]
        integrations_result = await db.execute(
            select(Integration).where(
                Integration.project_id.in_(project_ids),
                Integration.type == IntegrationType.vercel,
                Integration.status == IntegrationStatus.connected,
            )
        )
        source_urls_by_project_id = {}
        for integration in integrations_result.scalars().all():
            payload = ProjectService._decode_integration_payload(integration)
            source_url = payload.get("production_url") or payload.get("preview_url")
            if isinstance(source_url, str) and source_url.strip():
                source_urls_by_project_id[integration.project_id] = source_url.strip()

        await ThumbnailService.generate_for_projects(db, projects, source_urls_by_project_id)
        return await ProjectService.get_projects(db, user_id)

    @staticmethod
    async def update_project(db: AsyncSession, project_id: str, user_id: str, project_in: ProjectUpdate) -> Project:
        project = await ProjectService.get_project(db, project_id, user_id)
        
        update_data = project_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(project, field, value)
            
        await db.commit()
        await db.refresh(project)
        return project

    @staticmethod
    async def delete_project(db: AsyncSession, project_id: str, user_id: str):
        project = await ProjectService.get_project(db, project_id, user_id)
        await db.delete(project)
        await db.commit()
        return {"detail": "Project deleted successfully"}
