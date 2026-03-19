import socketio
from app.config import settings
from app.services.preview_manager import PreviewManager
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
        sio.enter_room(sid, project_id)
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
    
    # Notify room the agent is thinking
    await sio.emit("agent_typing", {"project_id": project_id}, to=sid)
    
    # Run the agent
    agent = EditorAgent()
    result = await agent.execute_edit(project_id, message)
    
    if "error" in result:
        await sio.emit("agent_reply", {
            "project_id": project_id,
            "message": f"Sorry, I encountered an error: {result['error']}"
        }, to=sid)
    else:
        await sio.emit("agent_reply", {
            "project_id": project_id,
            "message": result.get("reply", "I've updated the code for you.")
        }, to=sid)
        
        # Notify clients to trigger preview reload Native HMR handles reload mostly, but we can emit a refresh event
        await sio.emit("code_updated", {"project_id": project_id}, room=project_id)

