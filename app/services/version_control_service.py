import os
import subprocess
from datetime import datetime
from typing import List

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.project import ProjectCheckpoint


class VersionControlService:
    @staticmethod
    def _project_dir(project_id: str) -> str:
        if settings.USER_PROJECTS_DIR:
            target_dir = os.path.join(settings.USER_PROJECTS_DIR, project_id)
        else:
            backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            root_dir = os.path.dirname(backend_dir)
            target_dir = os.path.join(root_dir, "user_projects", project_id)

        if not os.path.exists(target_dir):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project directory not found")

        return target_dir

    @staticmethod
    def _run_git(args: List[str], cwd: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=True,
            )
            return (result.stdout or "").strip()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Git is not installed on the server") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or exc.stdout or "Git command failed").strip()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=stderr) from exc

    @staticmethod
    def _ensure_repo(cwd: str):
        git_dir = os.path.join(cwd, ".git")
        if not os.path.exists(git_dir):
            VersionControlService._run_git(["init"], cwd)
            VersionControlService._run_git(["config", "user.name", "ASEA Checkpoints"], cwd)
            VersionControlService._run_git(["config", "user.email", "checkpoints@asea.local"], cwd)

    @staticmethod
    async def create_checkpoint(db: AsyncSession, project_id: str, message: str) -> ProjectCheckpoint:
        project_dir = VersionControlService._project_dir(project_id)
        VersionControlService._ensure_repo(project_dir)

        VersionControlService._run_git(["add", "-A"], cwd=project_dir)
        commit_message = message.strip() if message and message.strip() else f"Checkpoint {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
        VersionControlService._run_git(["commit", "--allow-empty", "-m", commit_message], cwd=project_dir)
        commit_hash = VersionControlService._run_git(["rev-parse", "HEAD"], cwd=project_dir)

        checkpoint = ProjectCheckpoint(
            project_id=project_id,
            commit_hash=commit_hash,
            message=commit_message,
        )
        db.add(checkpoint)
        await db.commit()
        await db.refresh(checkpoint)
        return checkpoint

    @staticmethod
    async def list_checkpoints(db: AsyncSession, project_id: str) -> List[ProjectCheckpoint]:
        result = await db.execute(
            select(ProjectCheckpoint)
            .where(ProjectCheckpoint.project_id == project_id)
            .order_by(ProjectCheckpoint.created_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def restore_checkpoint(db: AsyncSession, project_id: str, checkpoint_id: str) -> ProjectCheckpoint:
        result = await db.execute(
            select(ProjectCheckpoint).where(
                ProjectCheckpoint.id == checkpoint_id,
                ProjectCheckpoint.project_id == project_id,
            )
        )
        checkpoint = result.scalars().first()
        if not checkpoint:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checkpoint not found")

        project_dir = VersionControlService._project_dir(project_id)
        VersionControlService._ensure_repo(project_dir)

        VersionControlService._run_git(["restore", "--source", checkpoint.commit_hash, "--staged", "--worktree", "."], cwd=project_dir)
        restore_message = f"Restore checkpoint: {checkpoint.message}"
        VersionControlService._run_git(["add", "-A"], cwd=project_dir)
        VersionControlService._run_git(["commit", "--allow-empty", "-m", restore_message], cwd=project_dir)

        return checkpoint
