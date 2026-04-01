from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.routers import auth, users, projects, requirements, specifications, generation, integrations
from app.socketio.server import socket_app

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions (e.g., connect to database, redis)
    yield
    # Shutdown actions (e.g., close connections)

app = FastAPI(
    title="ASEA Backend API",
    description="Backend for the ASEA Platform — AI-Powered E-Commerce Store Builder",
    version="0.1.0",
    lifespan=lifespan
)

# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.get("/")
async def root():
    return {"Welcome to the ASEA Backend API!"}  

@app.get("/health")
async def health_check():
    return {"status": "ok", "env": settings.APP_ENV}

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(projects.router, prefix="/api/v1/projects", tags=["Projects"])
app.include_router(
    requirements.router, 
    prefix="/api/v1/projects/{project_id}/requirements", 
    tags=["Requirements"]
)
app.include_router(
    specifications.router, 
    prefix="/api/v1/projects/{project_id}/specifications", 
    tags=["Specifications"]
)
app.include_router(
    generation.router, 
    prefix="/api/v1/projects/{project_id}/generation", 
    tags=["Generation"]
)
app.include_router(
    integrations.router,
    prefix="/api/v1/projects/{project_id}/integrations",
    tags=["Integrations"],
)

# Mount Socket.IO app
app.mount("/socket.io", socket_app)
