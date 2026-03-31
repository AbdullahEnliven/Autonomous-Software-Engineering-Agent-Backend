from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import ChatMessage


class ChatService:
    @staticmethod
    async def create_message(
        db: AsyncSession,
        project_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ChatMessage:
        message = ChatMessage(
            project_id=project_id,
            role=role,
            content=content,
            message_metadata=metadata or {},
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        return message

    @staticmethod
    async def get_messages(db: AsyncSession, project_id: str) -> List[ChatMessage]:
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.project_id == project_id)
            .order_by(ChatMessage.created_at.asc())
        )
        return result.scalars().all()
