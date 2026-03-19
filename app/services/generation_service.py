import os
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.project import GenerationJob, GenerationJobStatus, Specification
from app.services.integration_service import IntegrationService
from app.services.project_service import ProjectService
from app.tasks.generation_tasks import generate_store

class GenerationService:
    @staticmethod
    async def get_job(db: AsyncSession, job_id: str, project_id: str, user_id: str):
        await ProjectService.get_project(db, project_id, user_id)
        
        result = await db.execute(select(GenerationJob).where(
            GenerationJob.id == job_id,
            GenerationJob.project_id == project_id
        ))
        job = result.scalars().first()
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation job not found")
        return job

    @staticmethod
    async def start_generation(db: AsyncSession, project_id: str, specification_id: str, user_id: str):
        # 1. Verification
        await ProjectService.get_project(db, project_id, user_id)
        
        result = await db.execute(select(Specification).where(
            Specification.id == specification_id,
            Specification.project_id == project_id
        ))
        spec = result.scalars().first()
        
        if not spec:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Specification not found")
        
        if not spec.is_confirmed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Specification must be confirmed before generation"
            )

        # Supabase-first flow: generation is allowed only after connection is verified.
        # We allow an opt-out for offline generation so preview can still boot.
        require_supabase = os.getenv("ASEA_REQUIRE_SUPABASE", "false").lower() == "true"
        try:
            await IntegrationService.ensure_supabase_connected(db, project_id, user_id)
        except HTTPException as exc:
            if require_supabase:
                raise
            # Log-only fallback so we still generate a local preview without Supabase
            print(f"[GenerationService] Supabase not connected; proceeding offline. Detail: {exc.detail}")

        # check if active job exists
        active_job_result = await db.execute(select(GenerationJob).where(
            GenerationJob.project_id == project_id,
            GenerationJob.status.in_([GenerationJobStatus.pending, GenerationJobStatus.running])
        ))
        if active_job_result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An active generation job already exists for this project"
            )

        # 2. Create Job Record
        db_job = GenerationJob(
            project_id=project_id,
            specification_id=specification_id,
            status=GenerationJobStatus.pending,
            progress=0,
            current_step="Initializing generation pipeline"
        )
        db.add(db_job)
        await db.commit()
        await db.refresh(db_job)

        # 3. Queue Celery Task
        task = generate_store.delay(str(project_id), str(db_job.id), str(specification_id))
        
        db_job.celery_task_id = task.id
        await db.commit()
        await db.refresh(db_job)
        
        return db_job
