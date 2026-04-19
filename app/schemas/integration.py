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


class GithubOAuthUrlResponse(BaseModel):
    auth_url: str
    state: str


class GithubConnectRequest(BaseModel):
    code: str = Field(min_length=1)
    state: str = Field(min_length=1)


class GithubConnectResponse(BaseModel):
    connected: bool
    username: str


class GithubStatusResponse(BaseModel):
    connected: bool
    username: str | None = None
    connected_at: str | None = None


class GithubOrg(BaseModel):
    login: str
    id: int


class GithubOrgsResponse(BaseModel):
    orgs: list[GithubOrg]


class GithubPushRequest(BaseModel):
    repoName: str = Field(min_length=1)
    isPrivate: bool = True
    branch: str = Field(default="main", min_length=1)
    commitMessage: str = Field(default="Initial commit from ASEA", min_length=1)
    owner: str | None = None


class GithubPushResponse(BaseModel):
    url: str
    owner: str
    name: str
    branch: str
    created: bool
    committed_files: int
    skipped_files: int


class DeployRequest(BaseModel):
    subdomain: str | None = None
    target: str = "production"


class DeployResponse(BaseModel):
    status: str
    message: str
    url: str
    target: str
