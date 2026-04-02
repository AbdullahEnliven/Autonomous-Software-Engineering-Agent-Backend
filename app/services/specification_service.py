from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import json

from app.models.project import Specification, Requirement
from app.schemas.specification import SpecificationUpdate
from app.services.project_service import ProjectService
from app.agents.spec_agent import SpecificationAgent

class SpecificationService:
    @staticmethod
    async def get_specification(db: AsyncSession, spec_id: str, project_id: str, user_id: str):
        await ProjectService.get_project(db, project_id, user_id)
        
        result = await db.execute(select(Specification).where(
            Specification.id == spec_id, 
            Specification.project_id == project_id
        ))
        specification = result.scalars().first()
        if not specification:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Specification not found")
        return specification

    @staticmethod
    async def generate_specification(
        db: AsyncSession,
        requirement_id: str,
        project_id: str,
        user_id: str,
        forced_store_name: str | None = None,
    ):
        await ProjectService.get_project(db, project_id, user_id)
        
        result = await db.execute(select(Requirement).where(
            Requirement.id == requirement_id,
            Requirement.project_id == project_id
        ))
        requirement = result.scalars().first()
        if not requirement:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found")
            
        agent = SpecificationAgent()
        try:
            spec_dict = await agent.generate_specification(requirement)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to generate spec: {str(e)}")

        if forced_store_name and forced_store_name.strip():
            spec_dict["store_name"] = forced_store_name.strip()
            
        db_spec = Specification(
            project_id=project_id,
            requirement_id=requirement.id,
            store_name=spec_dict.get("store_name", "My Store"),
            tagline=spec_dict.get("tagline", ""),
            modules=spec_dict.get("modules", []),
            data_models=spec_dict.get("data_models", {}),
            pages=spec_dict.get("pages", []),
            features=spec_dict.get("features", {}),
            api_structure=spec_dict.get("api_structure", {}),
            raw_response=json.dumps(spec_dict)
        )
        
        db.add(db_spec)
        await db.commit()
        await db.refresh(db_spec)
        return db_spec

    @staticmethod
    async def update_specification(db: AsyncSession, spec_id: str, spec_in: SpecificationUpdate, project_id: str, user_id: str):
        specification = await SpecificationService.get_specification(db, spec_id, project_id, user_id)
        
        update_data = spec_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(specification, field, value)
            
        await db.commit()
        await db.refresh(specification)
        return specification
