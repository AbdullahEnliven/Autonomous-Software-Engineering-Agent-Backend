from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.project import Requirement, Project
from app.schemas.requirement import RequirementCreate, RequirementUpdate
from app.services.project_service import ProjectService

class RequirementService:
    @staticmethod
    async def get_requirements(db: AsyncSession, project_id: str, user_id: str):
        # Verify ownership
        await ProjectService.get_project(db, project_id, user_id)
        
        result = await db.execute(select(Requirement).where(Requirement.project_id == project_id))
        return result.scalars().all()

    @staticmethod
    async def get_requirement(db: AsyncSession, requirement_id: str, project_id: str, user_id: str):
        await ProjectService.get_project(db, project_id, user_id)
        
        result = await db.execute(select(Requirement).where(Requirement.id == requirement_id, Requirement.project_id == project_id))
        requirement = result.scalars().first()
        if not requirement:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found")
        return requirement

    @staticmethod
    async def create_requirement(db: AsyncSession, requirement_in: RequirementCreate, project_id: str, user_id: str):
        await ProjectService.get_project(db, project_id, user_id)
        
        db_requirement = Requirement(
            project_id=project_id,
            raw_text=requirement_in.raw_text,
            category=requirement_in.category,
            preferences=requirement_in.preferences
        )
        db.add(db_requirement)
        await db.commit()
        await db.refresh(db_requirement)
        return db_requirement

    @staticmethod
    async def update_requirement(db: AsyncSession, requirement_id: str, requirement_in: RequirementUpdate, project_id: str, user_id: str):
        requirement = await RequirementService.get_requirement(db, requirement_id, project_id, user_id)
        
        update_data = requirement_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(requirement, field, value)
            
        await db.commit()
        await db.refresh(requirement)
        return requirement
