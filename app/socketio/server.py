import socketio
from app.config import settings
from app.database import async_session_maker
from app.services.preview_manager import PreviewManager
from app.services.chat_service import ChatService
from app.services.version_control_service import VersionControlService
from app.agents.editor_agent import EditorAgent

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.CORS_ORIGINS,
    logger=True,
    engineio_logger=True,
)

socket_app = socketio.ASGIApp(sio)

# Track sid -> project_id mappings
client_projects = {}

@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")
    project_id = client_projects.pop(sid, None)
    if project_id:
        room_clients = sio.manager.rooms.get("/", {}).get(project_id, {})
        # If no clients are connected to this room, shut down the server
        if not room_clients:
            await PreviewManager.stop_preview(project_id)

@sio.on("join_project")
async def join_project(sid, data):
    project_id = data.get("project_id")
    if project_id:
        await sio.enter_room(sid, project_id)
        client_projects[sid] = project_id
        print(f"Client {sid} joined room: {project_id}")
        await sio.emit("notification", {"type": "info", "message": f"Joined project {project_id}"}, to=sid)
        
        # Start the preview server if it's not already running
        await PreviewManager.start_preview(project_id)

@sio.on("leave_project")
async def leave_project(sid, data):
    project_id = data.get("project_id")
    if project_id:
        sio.leave_room(sid, project_id)
        client_projects.pop(sid, None)
        print(f"Client {sid} left room: {project_id}")
        
        room_clients = sio.manager.rooms.get("/", {}).get(project_id, {})
        if not room_clients:
            await PreviewManager.stop_preview(project_id)

@sio.on("chat_message")
async def handle_chat_message(sid, data):
    project_id = data.get("project_id")
    message = data.get("message")
    
    if not project_id or not message:
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
            await ChatService.create_message(db, project_id, "user", message)
    except Exception as exc:
        print(f"Failed to persist user chat message: {exc}")
    
    # Notify room the agent is thinking
    await sio.emit("agent_typing", {"project_id": project_id}, to=sid)
    
    # Run the agent with Socket.IO access for real-time status events
    agent = EditorAgent()
    agent.sio = sio
    agent.sid = sid
    result = await agent.execute_edit(project_id, message)
    
    if "error" in result:
        error_message = f"Sorry, I encountered an error: {result['error']}"
        try:
            async with async_session_maker() as db:
                await ChatService.create_message(db, project_id, "agent", error_message, {"error": True})
        except Exception as exc:
            print(f"Failed to persist agent error message: {exc}")

        await sio.emit("agent_reply", {
            "project_id": project_id,
            "message": error_message,
            "files_modified": [],
            "plan": ""
        }, to=sid)
    else:
        agent_reply = result.get("reply", "I've updated the code for you.")
        try:
            async with async_session_maker() as db:
                await ChatService.create_message(
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

        await sio.emit("agent_reply", {
            "project_id": project_id,
            "message": agent_reply,
            "files_modified": result.get("files_modified", []),
            "plan": result.get("plan", "")
        }, to=sid)
        
        # Notify clients to trigger preview reload — HMR handles most, but emit refresh event
        await sio.emit("code_updated", {"project_id": project_id}, room=project_id)

