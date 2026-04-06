import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, BigInteger, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, TEXT, JSONB
from sqlalchemy.orm import relationship
import enum

from app.models.base import Base
from app.models.user import utc_now

class ProjectStatus(str, enum.Enum):
    draft = "draft"
    generating = "generating"
    ready = "ready"
    deployed = "deployed"

class GenerationJobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"

class IntegrationType(str, enum.Enum):
    supabase = "supabase"
    github = "github"
    vercel = "vercel"

class IntegrationStatus(str, enum.Enum):
    pending = "pending"
    connected = "connected"
    failed = "failed"


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    status = Column(SQLEnum(ProjectStatus), default=ProjectStatus.draft)
    thumbnail_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    owner = relationship("User", back_populates="projects")
    requirements = relationship("Requirement", back_populates="project", cascade="all, delete-orphan")
    specifications = relationship("Specification", back_populates="project", cascade="all, delete-orphan")
    generation_jobs = relationship("GenerationJob", back_populates="project", cascade="all, delete-orphan")
    files = relationship("ProjectFile", back_populates="project", cascade="all, delete-orphan")
    artifacts = relationship("Artifact", back_populates="project", cascade="all, delete-orphan")
    integrations = relationship("Integration", back_populates="project", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="project")
    chat_messages = relationship("ChatMessage", back_populates="project", cascade="all, delete-orphan")
    checkpoints = relationship("ProjectCheckpoint", back_populates="project", cascade="all, delete-orphan")


class Requirement(Base):
    __tablename__ = "requirements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    raw_text = Column(TEXT, nullable=False)
    enhanced_text = Column(TEXT, nullable=True)
    category = Column(String, nullable=True)
    preferences = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    project = relationship("Project", back_populates="requirements")
    specifications = relationship("Specification", back_populates="requirement")


class Specification(Base):
    __tablename__ = "specifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    requirement_id = Column(UUID(as_uuid=True), ForeignKey("requirements.id"), nullable=False)
    store_name = Column(String, nullable=False)
    tagline = Column(String, nullable=True)
    modules = Column(JSONB, nullable=False)
    data_models = Column(JSONB, nullable=False)
    pages = Column(JSONB, nullable=False)
    features = Column(JSONB, nullable=False)
    api_structure = Column(JSONB, nullable=False)
    raw_response = Column(TEXT, nullable=False)
    is_confirmed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    project = relationship("Project", back_populates="specifications")
    requirement = relationship("Requirement", back_populates="specifications")
    generation_jobs = relationship("GenerationJob", back_populates="specification")


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    specification_id = Column(UUID(as_uuid=True), ForeignKey("specifications.id"), nullable=False)
    celery_task_id = Column(String, nullable=True)
    status = Column(SQLEnum(GenerationJobStatus), default=GenerationJobStatus.pending)
    progress = Column(Integer, default=0)
    current_step = Column(String, nullable=True)
    logs = Column(JSONB, default=list)
    error_message = Column(TEXT, nullable=True)
    started_at = Column(DateTime(timezone=True), default=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="generation_jobs")
    specification = relationship("Specification", back_populates="generation_jobs")


class ProjectFile(Base):
    __tablename__ = "project_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    file_path = Column(String, nullable=False)
    content = Column(TEXT, nullable=False)
    language = Column(String, nullable=False)
    is_editable = Column(Boolean, default=False)
    last_edited_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="files")


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    storage_path = Column(String, nullable=False)
    file_size = Column(BigInteger, default=0)
    download_count = Column(Integer, default=0)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    project = relationship("Project", back_populates="artifacts")


class Integration(Base):
    __tablename__ = "integrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    type = Column(SQLEnum(IntegrationType), nullable=False)
    encrypted_credentials = Column(TEXT, nullable=False)
    status = Column(SQLEnum(IntegrationStatus), default=IntegrationStatus.pending)
    connected_at = Column(DateTime(timezone=True), default=utc_now)

    project = relationship("Project", back_populates="integrations")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    role = Column(String, nullable=False)  # user | agent
    content = Column(TEXT, nullable=False)
    message_metadata = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    project = relationship("Project", back_populates="chat_messages")


class ProjectCheckpoint(Base):
    __tablename__ = "project_checkpoints"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    commit_hash = Column(String, nullable=False)
    message = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    project = relationship("Project", back_populates="checkpoints")
