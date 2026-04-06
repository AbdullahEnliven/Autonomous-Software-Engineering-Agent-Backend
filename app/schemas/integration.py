from pydantic import BaseModel, Field


class SupabaseCredentials(BaseModel):
    url: str = Field(min_length=1)
    anonKey: str = Field(min_length=1)
    serviceRoleKey: str = Field(min_length=1)


class SupabaseConnectionResponse(BaseModel):
    connected: bool
    project_id: str
    type: str
    status: str
    url: str


class SupabaseStatusResponse(BaseModel):
    connected: bool
    project_id: str
    type: str
    status: str
    url: str | None = None


class SupabaseMigrationResponse(BaseModel):
    project_id: str
    status: str
    message: str


class VercelStatusResponse(BaseModel):
    configured: bool
    connected: bool
    project_id: str
    type: str
    status: str
    preview_url: str | None = None
    production_url: str | None = None


class DeployRequest(BaseModel):
    subdomain: str | None = None
    target: str = "production"


class DeployResponse(BaseModel):
    status: str
    message: str
    url: str
    target: str
