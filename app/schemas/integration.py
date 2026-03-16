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
