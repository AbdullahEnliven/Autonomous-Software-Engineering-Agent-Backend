import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, TEXT
from sqlalchemy.orm import relationship
import enum

from app.models.base import Base

def utc_now():
    return datetime.now(timezone.utc)

class UserPlan(str, enum.Enum):
    free = "free"
    pro = "pro"
    team = "team"

class NotificationType(str, enum.Enum):
    info = "info"
    success = "success"
    warning = "warning"
    error = "error"

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    plan = Column(SQLEnum(UserPlan), default=UserPlan.free)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")
    github_connections = relationship("GithubConnection", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")


class GithubConnection(Base):
    __tablename__ = "github_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    github_username = Column(String, nullable=False)
    encrypted_access_token = Column(TEXT, nullable=False)
    connected_at = Column(DateTime(timezone=True), default=utc_now)

    user = relationship("User", back_populates="github_connections")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    message = Column(TEXT, nullable=False)
    type = Column(SQLEnum(NotificationType), default=NotificationType.info)
    is_read = Column(Boolean, default=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    user = relationship("User", back_populates="notifications")
    project = relationship("Project", back_populates="notifications")
