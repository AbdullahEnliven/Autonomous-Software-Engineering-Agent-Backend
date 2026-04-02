from pathlib import Path

from app.config import settings


def get_backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def get_user_projects_dir() -> Path:
    if settings.USER_PROJECTS_DIR:
        return Path(settings.USER_PROJECTS_DIR).resolve()
    return get_backend_dir() / "user_projects"


def get_project_dir(project_id: str) -> Path:
    return get_user_projects_dir() / str(project_id)


def get_template_dir() -> Path:
    if settings.TEMPLATE_DIR:
        return Path(settings.TEMPLATE_DIR).resolve()
    return get_backend_dir() / "template" / "ASEA-Template"
