import os
import time
import asyncio
from app.tasks.celery_app import celery_app
from app.database import async_session_maker
from app.models.project import GenerationJob, Specification, GenerationJobStatus, Requirement
from sqlalchemy import select
from app.utils.template_editor import create_project_from_template
from app.utils.paths import get_project_dir, get_template_dir

async def async_generate_store(project_id: str, job_id: str, specification_id: str):
    print(f"Starting async store generation for project {project_id}, job {job_id}")

    async with async_session_maker() as db:
        try:
            # Get Job and Specification
            job_result = await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
            job = job_result.scalars().first()
            
            spec_result = await db.execute(select(Specification).where(Specification.id == specification_id))
            spec = spec_result.scalars().first()

            requirement = None
            if spec:
                requirement_result = await db.execute(select(Requirement).where(Requirement.id == spec.requirement_id))
                requirement = requirement_result.scalars().first()
            
            if not job or not spec:
                print("Job or Specification not found.")
                return {"status": "failed", "error": "Job or spec not found"}

            job.status = GenerationJobStatus.running
            job.progress = 10
            job.current_step = "Cloning base template"
            await db.commit()

            # Paths
            target_dir = str(get_project_dir(project_id))
            template_dir = get_template_dir()

            # Clone and edit template
            config = {
                'store_name': spec.store_name,
                'tagline': spec.tagline or 'Powered by ASEA',
                'store_description': requirement.raw_text if requirement and requirement.raw_text else (spec.tagline or spec.store_name),
                'hero_badge': spec.store_name,
                'hero_title': f"{spec.store_name} — {spec.tagline}" if spec.tagline else f"{spec.store_name} Storefront",
                'hero_subtitle': spec.tagline or 'A modern storefront built for you.',
                'hero_cta': 'Shop Now',
            }
            
            # This is synchronous but okay for a celery worker
            create_project_from_template(
                base_dir=str(template_dir.parent),
                template_name=template_dir.name,
                target_dir=target_dir, 
                config=config
            )

            job.progress = 40
            job.current_step = "Applying module modifications"
            await db.commit()
            await asyncio.sleep(2)

            job.progress = 70
            job.current_step = "Booting Preview Environment"
            await db.commit()
            
            import subprocess
            import hashlib
            
            base_hash = int(hashlib.md5(str(project_id).encode()).hexdigest(), 16)
            port = 6000 + (base_hash % 3000)

            # Windows specifically: kill existing process on this port
            subprocess.run(f'FOR /F "tokens=5" %a IN (\'netstat -aon ^| findstr :{port}\') DO taskkill /F /PID %a', shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

            node_modules_src = os.path.join(str(template_dir), 'node_modules')
            node_modules_dst = os.path.join(target_dir, 'node_modules')
            if os.path.exists(node_modules_src) and not os.path.exists(node_modules_dst):
                subprocess.run(['cmd', '/c', 'mklink', '/J', node_modules_dst, node_modules_src], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

            print(f"Starting Vite dev server on port {port}...")
            # We use npx.cmd on windows
            subprocess.Popen(f'npx.cmd vite --port {port}', cwd=target_dir, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            await asyncio.sleep(4) # Wait for Vite to boot

            job.progress = 100
            job.status = GenerationJobStatus.complete
            job.current_step = "Generation completed successfully"
            await db.commit()

            print(f"Completed store generation for project {project_id} at {target_dir}")
            return {"status": "success", "project_id": project_id, "path": target_dir}

        except Exception as e:
            print(f"Error during generation: {e}")
            if 'job' in locals() and job:
                job.status = GenerationJobStatus.failed
                job.current_step = f"Failed: {str(e)}"
                await db.commit()
            return {"status": "failed", "error": str(e)}

@celery_app.task(bind=True, max_retries=2, name="tasks.generate_store")
def generate_store(self, project_id: str, job_id: str, specification_id: str):
    return asyncio.run(async_generate_store(project_id, job_id, specification_id))

@celery_app.task(name="tasks.package_artifact")
def package_artifact(project_id: str):
    pass
