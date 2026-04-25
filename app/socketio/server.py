import asyncio
import time
from typing import Dict, Optional, Set

import socketio
from jose import JWTError, jwt
from sqlalchemy import select

from app.config import settings
from app.database import async_session_maker
from app.models.project import Project
from app.services.preview_manager import PreviewManager
from app.services.chat_service import ChatService
from app.services.version_control_service import VersionControlService
from app.agents.editor_agent import EditorAgent
from app.utils.security import ALGORITHM

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.CORS_ORIGINS,
    logger=True,
    engineio_logger=True,
)

socket_app = socketio.ASGIApp(sio)

# Track sid -> {project_id, ...} mappings to support one client joining multiple projects.
client_projects: Dict[str, Set[str]] = {}
# Optional authenticated user id extracted from socket auth token.
client_users: Dict[str, str] = {}
# Serialize edit operations per project to prevent concurrent write collisions.
project_edit_locks: Dict[str, asyncio.Lock] = {}


def _extract_token(environ, auth_payload) -> Optional[str]:
    if isinstance(auth_payload, dict):
        token = auth_payload.get("token")
        if token:
            return str(token)

    auth_header = environ.get("HTTP_AUTHORIZATION") if isinstance(environ, dict) else None
    if isinstance(auth_header, str) and auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()

    return None


def _decode_user_id_from_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        return str(user_id) if user_id else None
    except JWTError:
        return None


async def _user_can_access_project(project_id: str, user_id: Optional[str]) -> bool:
    if not project_id:
        return False

    async with async_session_maker() as db:
        stmt = select(Project.id).where(Project.id == project_id)
        if user_id:
            stmt = stmt.where(Project.user_id == user_id)

        result = await db.execute(stmt)
        return result.scalar_one_or_none() is not None


def _get_project_lock(project_id: str) -> asyncio.Lock:
    lock = project_edit_locks.get(project_id)
    if lock is None:
        lock = asyncio.Lock()
        project_edit_locks[project_id] = lock
    return lock

@sio.event
async def connect(sid, environ, auth=None):
    token = _extract_token(environ, auth)
    user_id = _decode_user_id_from_token(token)
    if user_id:
        client_users[sid] = user_id
    print(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")
    joined_projects = client_projects.pop(sid, set())
    client_users.pop(sid, None)

    for project_id in joined_projects:
        await PreviewManager.unregister_viewer(project_id, sid)
        await PreviewManager.stop_if_idle(project_id)

@sio.on("join_project")
async def join_project(sid, data):
    project_id = data.get("project_id")
    if not project_id:
        return

    user_id = client_users.get(sid)
    if not await _user_can_access_project(project_id, user_id):
        await sio.emit(
            "notification",
            {"type": "error", "message": "Unauthorized or unknown project."},
            to=sid,
        )
        return

    await sio.enter_room(sid, project_id)
    client_projects.setdefault(sid, set()).add(project_id)
    await PreviewManager.register_viewer(project_id, sid)
    print(f"Client {sid} joined room: {project_id}")
    await sio.emit("notification", {"type": "info", "message": f"Joined project {project_id}"}, to=sid)

    # Start the preview server if it's not already running.
    await PreviewManager.start_preview(project_id)

@sio.on("leave_project")
async def leave_project(sid, data):
    project_id = data.get("project_id")
    if not project_id:
        return

    await sio.leave_room(sid, project_id)
    joined_projects = client_projects.get(sid)
    if joined_projects:
        joined_projects.discard(project_id)
        if not joined_projects:
            client_projects.pop(sid, None)

    await PreviewManager.unregister_viewer(project_id, sid)
    await PreviewManager.stop_if_idle(project_id)
    print(f"Client {sid} left room: {project_id}")

@sio.on("chat_message")
async def handle_chat_message(sid, data):
    project_id = data.get("project_id")
    message = data.get("message")
    
    if not project_id or not message:
        return

    user_id = client_users.get(sid)
    if not await _user_can_access_project(project_id, user_id):
        await sio.emit(
            "notification",
            {"type": "error", "message": "You do not have access to this project."},
            to=sid,
        )
        return

    if project_id not in client_projects.get(sid, set()):
        await sio.emit(
            "notification",
            {"type": "error", "message": "Join the project room before sending chat."},
            to=sid,
        )
        return
        
    print(f"Received chat from {sid} for project {project_id}: {message}")

    # Each chat message becomes a git checkpoint (best effort).
    checkpoint_message = f"Chat checkpoint: {message.strip()[:120]}"
    try:
        async with async_session_maker() as db:
            await VersionControlService.create_checkpoint(db, project_id, checkpoint_message)
    except Exception as exc:
        print(f"Failed to create chat checkpoint: {exc}")

    # Save user message to persistent chat history.
    try:
        async with async_session_maker() as db:
            await ChatService.create_message(
                db,
                project_id,
                "user",
                message,
                {
                    "sid": sid,
                    "user_id": user_id,
                    "received_at": int(time.time()),
                },
            )
    except Exception as exc:
        print(f"Failed to persist user chat message: {exc}")

    lock = _get_project_lock(project_id)
    if lock.locked():
        await sio.emit(
            "agent_status",
            {
                "type": "queued",
                "message": "Another edit is in progress for this project. Your request is queued.",
                "details": {},
            },
            to=sid,
        )

    async with lock:
        # Notify room the agent is thinking.
        await sio.emit("agent_typing", {"project_id": project_id}, room=project_id)

        # Run the agent with Socket.IO access for real-time status events.
        agent = EditorAgent()
        agent.sio = sio
        agent.sid = sid
        result = await agent.execute_edit(project_id, message)
    
        if "error" in result:
            error_message = f"Sorry, I encountered an error: {result['error']}"
            persisted = None
            try:
                async with async_session_maker() as db:
                    persisted = await ChatService.create_message(db, project_id, "agent", error_message, {"error": True})
            except Exception as exc:
                print(f"Failed to persist agent error message: {exc}")

            await sio.emit("agent_reply", {
                "project_id": project_id,
                "id": str(persisted.id) if persisted else None,
                "role": "agent",
                "message": error_message,
                "files_modified": [],
                "plan": ""
            }, room=project_id)
            return

        agent_reply = result.get("reply", "I've updated the code for you.")
        persisted = None
        try:
            async with async_session_maker() as db:
                persisted = await ChatService.create_message(
                    db,
                    project_id,
                    "agent",
                    agent_reply,
                    {
                        "files_modified": result.get("files_modified", []),
                        "plan": result.get("plan", ""),
                    },
                )
        except Exception as exc:
            print(f"Failed to persist agent reply: {exc}")

        await PreviewManager.touch_project(project_id)
        await sio.emit("agent_reply", {
            "project_id": project_id,
            "id": str(persisted.id) if persisted else None,
            "role": "agent",
            "message": agent_reply,
            "files_modified": result.get("files_modified", []),
            "plan": result.get("plan", "")
        }, room=project_id)

        # Notify clients to trigger preview refresh UX; Vite HMR still handles direct code pushes.
        await sio.emit(
            "code_updated",
            {"project_id": project_id, "updated_at": int(time.time() * 1000)},
            room=project_id,
        )

