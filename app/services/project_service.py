from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
import uuid

from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate

class ProjectService:
    @staticmethod
    async def get_projects(db: AsyncSession, user_id: str):
        result = await db.execute(
            select(Project)
            .where(Project.user_id == user_id)
            .order_by(Project.created_at.desc())
        )
        return result.scalars().all()

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
        return db_project

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
