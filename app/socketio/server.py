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
from app.services.integration_service import IntegrationService
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
        # Vercel previews are persistent — no local processes to stop

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

    # Emit current Vercel preview status so the frontend knows the state immediately
    preview_status = PreviewManager.get_status(project_id)
    await sio.emit("preview_status", preview_status, to=sid)

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

    client_message_id = data.get("client_message_id")
    pre_edit_checkpoint = None

    # Each user prompt gets a restore point, but it should not create an extra Git commit.
    checkpoint_message = f"Before chat edit: {message.strip()[:120]}"
    try:
        async with async_session_maker() as db:
            pre_edit_checkpoint = await VersionControlService.record_current_checkpoint(db, project_id, checkpoint_message)
    except Exception as exc:
        print(f"Failed to create chat checkpoint: {exc}")

    # Save user message to persistent chat history.
    try:
        async with async_session_maker() as db:
            user_metadata = {
                "sid": sid,
                "user_id": user_id,
                "received_at": int(time.time()),
                "client_message_id": client_message_id,
            }
            if pre_edit_checkpoint:
                user_metadata.update(
                    {
                        "checkpoint_id": str(pre_edit_checkpoint.id),
                        "commit_hash": pre_edit_checkpoint.commit_hash,
                        "checkpoint_message": pre_edit_checkpoint.message,
                    }
                )

            persisted_user = await ChatService.create_message(
                db,
                project_id,
                "user",
                message,
                user_metadata,
            )
            await sio.emit(
                "chat_message_saved",
                {
                    "project_id": project_id,
                    "id": str(persisted_user.id),
                    "client_message_id": client_message_id,
                    "role": "user",
                    "message": message,
                    "metadata": user_metadata,
                },
                room=project_id,
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

        # Fetch recent chat history for LLM context.
        recent_history = []
        try:
            async with async_session_maker() as db:
                all_msgs = await ChatService.get_messages(db, project_id)
                recent_history = [
                    {"role": m.role, "content": m.content}
                    for m in (all_msgs[-6:] if len(all_msgs) > 6 else all_msgs)
                ]
        except Exception as exc:
            print(f"Failed to load chat history for agent context: {exc}")

        # Run the agent with Socket.IO access for real-time status events.
        agent = EditorAgent()
        agent.sio = sio
        agent.sid = sid
        result = await agent.execute_edit(project_id, message, chat_history=recent_history)

        if "error" in result:
            error_message = f"Sorry, I encountered an error: {result['error']}"
            persisted = None
            try:
                async with async_session_maker() as db:
                    persisted = await ChatService.create_message(db, project_id, "agent", error_message, {"error": True})
            except Exception as exc:
                print(f"Failed to persist agent error message: {exc}")

            if result.get("rolled_back"):
                # Invalidate preview cache so next view triggers fresh deploy
                await PreviewManager.restart_preview(project_id)
                await sio.emit(
                    "code_updated",
                    {
                        "project_id": project_id,
                        "updated_at": int(time.time() * 1000),
                        "rolled_back": True,
                        "restored_files": result.get("restored_files", []),
                    },
                    room=project_id,
                )

            await sio.emit("agent_reply", {
                "project_id": project_id,
                "id": str(persisted.id) if persisted else None,
                "role": "agent",
                "message": error_message,
                "files_modified": [],
                "plan": "",
                "rolled_back": result.get("rolled_back", False),
                "restored_files": result.get("restored_files", []),
            }, room=project_id)
            return

        agent_reply = result.get("reply", "I've updated the code for you.")
        post_edit_checkpoint = None
        github_push = {"pushed": False, "reason": "repo_not_configured"}

        try:
            async with async_session_maker() as db:
                post_edit_checkpoint = await VersionControlService.create_checkpoint(
                    db,
                    project_id,
                    f"Chat response: {message.strip()[:100]}",
                )
                if user_id:
                    try:
                        github_push = await IntegrationService.auto_push_connected_repo(db, project_id, user_id)
                    except Exception as exc:
                        detail = getattr(exc, "detail", str(exc))
                        github_push = {"pushed": False, "error": str(detail)}
                        print(f"Failed to auto-push chat checkpoint: {detail}")
                else:
                    github_push = {"pushed": False, "reason": "socket_not_authenticated"}
        except Exception as exc:
            github_push = {"pushed": False, "error": str(exc)}
            print(f"Failed to create post-edit chat checkpoint: {exc}")

        persisted = None
        try:
            async with async_session_maker() as db:
                agent_metadata = {
                    "files_modified": result.get("files_modified", []),
                    "plan": result.get("plan", ""),
                    "github_push": github_push,
                }
                if post_edit_checkpoint:
                    agent_metadata.update(
                        {
                            "checkpoint_id": str(post_edit_checkpoint.id),
                            "commit_hash": post_edit_checkpoint.commit_hash,
                            "checkpoint_message": post_edit_checkpoint.message,
                        }
                    )

                persisted = await ChatService.create_message(
                    db,
                    project_id,
                    "agent",
                    agent_reply,
                    agent_metadata,
                )
        except Exception as exc:
            print(f"Failed to persist agent reply: {exc}")

        # Invalidate preview — user will see "code changed" state.
        # The next time they open the preview tab, a fresh Vercel deploy will be triggered.
        await PreviewManager.restart_preview(project_id)
        await sio.emit("agent_reply", {
            "project_id": project_id,
            "id": str(persisted.id) if persisted else None,
            "role": "agent",
            "message": agent_reply,
            "files_modified": result.get("files_modified", []),
            "plan": result.get("plan", ""),
            "checkpoint_id": str(post_edit_checkpoint.id) if post_edit_checkpoint else None,
            "commit_hash": post_edit_checkpoint.commit_hash if post_edit_checkpoint else None,
            "github_push": github_push,
        }, room=project_id)

        # Notify clients that preview needs refresh
        await sio.emit(
            "preview_status",
            {"status": "idle", "url": None, "message": "Code updated — click Preview to refresh"},
            room=project_id,
        )
        await sio.emit(
            "code_updated",
            {
                "project_id": project_id,
                "updated_at": int(time.time() * 1000),
                "checkpoint_id": str(post_edit_checkpoint.id) if post_edit_checkpoint else None,
                "commit_hash": post_edit_checkpoint.commit_hash if post_edit_checkpoint else None,
                "github_push": github_push,
            },
            room=project_id,
        )

