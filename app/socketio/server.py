import socketio
from app.config import settings

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.CORS_ORIGINS,
    logger=True,
    engineio_logger=True,
)

socket_app = socketio.ASGIApp(sio)

@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")

@sio.on("join_project")
async def join_project(sid, data):
    project_id = data.get("project_id")
    if project_id:
        sio.enter_room(sid, project_id)
        print(f"Client {sid} joined room: {project_id}")
        await sio.emit("notification", {"type": "info", "message": f"Joined project {project_id}"}, to=sid)

@sio.on("leave_project")
async def leave_project(sid, data):
    project_id = data.get("project_id")
    if project_id:
        sio.leave_room(sid, project_id)
        print(f"Client {sid} left room: {project_id}")
