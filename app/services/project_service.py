from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
import uuid
import html
from urllib.parse import quote

from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate

class ProjectService:
    @staticmethod
    def _build_svg_thumbnail(project_name: str, subtitle: str) -> str:
        safe_name = html.escape((project_name or "New Store").strip()[:42])
        safe_subtitle = html.escape((subtitle or "Preview unavailable").strip()[:52])
        initials = "".join([word[0] for word in (project_name or "New Store").split()[:2]]).upper() or "NS"

        svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='800' viewBox='0 0 1200 800'>
<defs>
  <linearGradient id='bg' x1='0' y1='0' x2='1' y2='1'>
    <stop offset='0%' stop-color='#111827'/>
    <stop offset='55%' stop-color='#0f172a'/>
    <stop offset='100%' stop-color='#111111'/>
  </linearGradient>
</defs>
<rect width='1200' height='800' fill='url(#bg)'/>
<circle cx='1020' cy='110' r='180' fill='rgba(59,130,246,0.18)'/>
<circle cx='170' cy='700' r='220' fill='rgba(16,185,129,0.16)'/>
<rect x='130' y='190' width='940' height='420' rx='24' fill='rgba(255,255,255,0.06)' stroke='rgba(255,255,255,0.18)'/>
<rect x='170' y='245' width='96' height='96' rx='18' fill='rgba(255,255,255,0.14)'/>
<text x='218' y='305' text-anchor='middle' font-size='42' fill='white' font-family='Arial, sans-serif' font-weight='700'>{initials}</text>
<text x='170' y='395' font-size='58' fill='white' font-family='Arial, sans-serif' font-weight='700'>{safe_name}</text>
<text x='170' y='448' font-size='30' fill='rgba(255,255,255,0.72)' font-family='Arial, sans-serif'>{safe_subtitle}</text>
<text x='170' y='562' font-size='22' fill='rgba(255,255,255,0.55)' font-family='Arial, sans-serif'>ASEA auto-generated project preview</text>
</svg>"""

        return f"data:image/svg+xml;charset=UTF-8,{quote(svg)}"

    @staticmethod
    def build_generated_thumbnail_url(project_name: str) -> str:
        return ProjectService._build_svg_thumbnail(project_name, "Generated successfully")

    @staticmethod
    def build_deployed_thumbnail_url(project_name: str, deploy_url: str | None) -> str:
        if deploy_url and str(deploy_url).startswith("http"):
            # Use a simple screenshot proxy to represent the latest deployed storefront.
            return f"https://image.thum.io/get/width/1200/noanimate/{deploy_url}"
        return ProjectService._build_svg_thumbnail(project_name, "Deployed successfully")

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
