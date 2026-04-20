import json
import base64
import asyncio
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import HTTPException, status
from github import Github, GithubException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.project import Integration, IntegrationStatus, IntegrationType
from app.models.user import GithubConnection
from app.config import settings
from app.schemas.integration import SupabaseCredentials
from app.services.project_service import ProjectService
from app.utils.paths import get_project_dir


class IntegrationService:
    IGNORED_DIRS = {".git", "node_modules", "dist", "build", "__pycache__", ".pytest_cache"}

    @staticmethod
    async def _get_integration(
        db: AsyncSession, project_id: str, integration_type: IntegrationType
    ) -> Integration | None:
        result = await db.execute(
            select(Integration).where(
                Integration.project_id == project_id,
                Integration.type == integration_type,
            )
        )
        return result.scalars().first()

    @staticmethod
    async def _get_github_connection(db: AsyncSession, user_id: str) -> GithubConnection | None:
        result = await db.execute(
            select(GithubConnection)
            .where(GithubConnection.user_id == user_id)
            .order_by(GithubConnection.connected_at.desc())
        )
        return result.scalars().first()

    @staticmethod
    def _encode_github_state(project_id: str, user_id: str) -> str:
        payload = json.dumps({"project_id": project_id, "user_id": user_id, "ts": datetime.utcnow().timestamp()})
        return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8").rstrip("=")

    @staticmethod
    def _decode_github_state(state: str) -> dict:
        try:
            padded = state + "=" * (-len(state) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
            payload = json.loads(decoded)
            if not isinstance(payload, dict):
                raise ValueError("Invalid state payload")
            return payload
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid GitHub OAuth state") from exc

    @staticmethod
    def _collect_project_files(project_dir: Path) -> list[Path]:
        files: list[Path] = []
        for path in project_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(project_dir).as_posix()
            parts = rel.split("/")
            if any(part in IntegrationService.IGNORED_DIRS for part in parts):
                continue
            files.append(path)
        return files

    @staticmethod
    def _push_repository_contents(
        *,
        access_token: str,
        repo_name: str,
        owner: str | None,
        is_private: bool,
        branch: str,
        commit_message: str,
        project_dir: Path,
    ) -> dict:
        gh = Github(access_token)
        user = gh.get_user()
        target_owner = owner.strip() if owner else user.login
        created = False

        if target_owner.lower() == user.login.lower():
            namespace = user
        else:
            namespace = gh.get_organization(target_owner)

        full_repo_name = f"{target_owner}/{repo_name}"
        try:
            repo = gh.get_repo(full_repo_name)
        except GithubException as exc:
            if exc.status != 404:
                raise
            repo = namespace.create_repo(name=repo_name, private=is_private, auto_init=True)
            created = True

        default_branch = repo.default_branch or "main"
        target_branch = (branch or default_branch).strip()
        if not target_branch:
            target_branch = default_branch

        try:
            repo.get_branch(target_branch)
        except GithubException as exc:
            if exc.status != 404:
                raise
            base_sha = repo.get_branch(default_branch).commit.sha
            repo.create_git_ref(ref=f"refs/heads/{target_branch}", sha=base_sha)

        committed_files = 0
        skipped_files = 0

        for file_path in IntegrationService._collect_project_files(project_dir):
            rel = file_path.relative_to(project_dir).as_posix()
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                skipped_files += 1
                continue

            try:
                existing = repo.get_contents(rel, ref=target_branch)
                repo.update_file(
                    path=rel,
                    message=commit_message,
                    content=content,
                    sha=existing.sha,
                    branch=target_branch,
                )
            except GithubException as exc:
                if exc.status == 404:
                    repo.create_file(rel, commit_message, content, branch=target_branch)
                else:
                    raise

            committed_files += 1

        return {
            "url": repo.html_url,
            "owner": target_owner,
            "name": repo.name,
            "branch": target_branch,
            "created": created,
            "committed_files": committed_files,
            "skipped_files": skipped_files,
        }

    @staticmethod
    async def _get_supabase_integration(db: AsyncSession, project_id: str) -> Integration | None:
        return await IntegrationService._get_integration(db, project_id, IntegrationType.supabase)

    @staticmethod
    async def _verify_supabase_credentials(credentials: SupabaseCredentials) -> None:
        base_url = credentials.url.rstrip("/")
        # Hit the health check endpoint or just request an empty query on the projects metadata
        # We can just request from /rest/v1/?apikey=...
        endpoint = f"{base_url}/rest/v1/"
        headers = {
            "apikey": credentials.anonKey,
            "Authorization": f"Bearer {credentials.anonKey}",
            "Accept-Profile": "public"
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(endpoint, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Supabase connection failed: {str(exc)}",
            ) from exc

        if response.status_code >= 400:
            print(f"Supabase returned status {response.status_code}: {response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid Supabase credentials or project URL. Status: {response.status_code}, Body: {response.text}",
            )

    @staticmethod
    async def get_supabase_status(db: AsyncSession, project_id: str, user_id: str) -> dict:
        await ProjectService.get_project(db, project_id, user_id)
        integration = await IntegrationService._get_supabase_integration(db, project_id)
        if not integration:
            return {
                "connected": False,
                "project_id": project_id,
                "type": IntegrationType.supabase.value,
                "status": IntegrationStatus.pending.value,
                "url": None,
            }

        parsed = {}
        try:
            parsed = json.loads(integration.encrypted_credentials or "{}")
        except json.JSONDecodeError:
            parsed = {}

        return {
            "connected": integration.status == IntegrationStatus.connected,
            "project_id": project_id,
            "type": integration.type.value,
            "status": integration.status.value,
            "url": parsed.get("url"),
        }

    @staticmethod
    async def test_supabase_connection(
        db: AsyncSession, project_id: str, user_id: str, credentials: SupabaseCredentials
    ) -> dict:
        await ProjectService.get_project(db, project_id, user_id)
        await IntegrationService._verify_supabase_credentials(credentials)

        integration = await IntegrationService._get_supabase_integration(db, project_id)
        payload = {
            "url": credentials.url,
            "anonKey": credentials.anonKey,
            "serviceRoleKey": credentials.serviceRoleKey,
        }

        if integration is None:
            integration = Integration(
                project_id=project_id,
                type=IntegrationType.supabase,
                encrypted_credentials=json.dumps(payload),
                status=IntegrationStatus.connected,
                connected_at=datetime.utcnow(),
            )
            db.add(integration)
        else:
            integration.encrypted_credentials = json.dumps(payload)
            integration.status = IntegrationStatus.connected
            integration.connected_at = datetime.utcnow()

        await db.commit()

        return {
            "connected": True,
            "project_id": project_id,
            "type": IntegrationType.supabase.value,
            "status": IntegrationStatus.connected.value,
            "url": credentials.url,
        }

    @staticmethod
    async def run_supabase_migrations(
        db: AsyncSession, project_id: str, user_id: str, credentials: SupabaseCredentials
    ) -> dict:
        await IntegrationService.test_supabase_connection(db, project_id, user_id, credentials)
        return {
            "project_id": project_id,
            "status": "ok",
            "message": "Supabase connection verified. Migration execution hook is ready.",
        }

    @staticmethod
    async def run_supabase_seed(db: AsyncSession, project_id: str, user_id: str) -> dict:
        await IntegrationService.ensure_supabase_connected(db, project_id, user_id)
        return {
            "project_id": project_id,
            "status": "ok",
            "message": "Seed execution hook is ready.",
        }

    @staticmethod
    async def ensure_supabase_connected(db: AsyncSession, project_id: str, user_id: str) -> None:
        await ProjectService.get_project(db, project_id, user_id)
        integration = await IntegrationService._get_supabase_integration(db, project_id)
        if not integration or integration.status != IntegrationStatus.connected:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Connect your Supabase project before generation.",
            )

    @staticmethod
    async def get_vercel_status(db: AsyncSession, project_id: str, user_id: str, configured: bool) -> dict:
        await ProjectService.get_project(db, project_id, user_id)
        integration = await IntegrationService._get_integration(db, project_id, IntegrationType.vercel)

        if not integration:
            return {
                "configured": configured,
                "connected": False,
                "project_id": project_id,
                "type": IntegrationType.vercel.value,
                "status": IntegrationStatus.pending.value,
                "preview_url": None,
                "production_url": None,
            }

        parsed = {}
        try:
            parsed = json.loads(integration.encrypted_credentials or "{}")
        except json.JSONDecodeError:
            parsed = {}

        return {
            "configured": configured,
            "connected": integration.status == IntegrationStatus.connected,
            "project_id": project_id,
            "type": integration.type.value,
            "status": integration.status.value,
            "preview_url": parsed.get("preview_url"),
            "production_url": parsed.get("production_url"),
        }

    @staticmethod
    async def get_github_oauth_url(db: AsyncSession, project_id: str, user_id: str) -> dict:
        await ProjectService.get_project(db, project_id, user_id)
        if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
            raise HTTPException(status_code=400, detail="GitHub OAuth is not configured")

        state = IntegrationService._encode_github_state(project_id, user_id)
        params = {
            "client_id": settings.GITHUB_CLIENT_ID,
            "redirect_uri": settings.GITHUB_REDIRECT_URI,
            "scope": "repo read:user read:org",
            "state": state,
            "allow_signup": "true",
        }
        auth_url = httpx.URL("https://github.com/login/oauth/authorize", params=params)
        return {"auth_url": str(auth_url), "state": state}

    @staticmethod
    async def connect_github(db: AsyncSession, project_id: str, user_id: str, code: str, state: str) -> dict:
        await ProjectService.get_project(db, project_id, user_id)
        payload = IntegrationService._decode_github_state(state)
        state_project_id = str(payload.get("project_id", ""))
        state_user_id = str(payload.get("user_id", ""))

        if state_project_id != str(project_id) or state_user_id != str(user_id):
            raise HTTPException(status_code=400, detail="OAuth state does not match this project")

        token_payload = {
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.GITHUB_REDIRECT_URI,
            "state": state,
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                token_res = await client.post(
                    "https://github.com/login/oauth/access_token",
                    json=token_payload,
                    headers={"Accept": "application/json"},
                )
                token_res.raise_for_status()
                token_data = token_res.json()
                access_token = token_data.get("access_token")
                if not access_token:
                    detail = token_data.get("error_description") or "Failed to retrieve access token"
                    raise HTTPException(status_code=400, detail=detail)

                user_res = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "ASEA-App",
                    },
                )
                if user_res.status_code >= 400:
                    raise HTTPException(status_code=400, detail=f"GitHub API Error: {user_res.status_code} {user_res.text}")
                user_res.raise_for_status()
                gh_user = user_res.json()
        except HTTPException:
            raise
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=400, detail=f"GitHub OAuth failed: {exc}") from exc

        github_username = gh_user.get("login")
        if not github_username:
            raise HTTPException(status_code=400, detail="GitHub user profile is missing login")

        connection = await IntegrationService._get_github_connection(db, user_id)
        if connection is None:
            connection = GithubConnection(
                user_id=user_id,
                github_username=github_username,
                encrypted_access_token=access_token,
                connected_at=datetime.utcnow(),
            )
            db.add(connection)
        else:
            connection.github_username = github_username
            connection.encrypted_access_token = access_token
            connection.connected_at = datetime.utcnow()

        integration = await IntegrationService._get_integration(db, project_id, IntegrationType.github)
        integration_payload = {
            "github_username": github_username,
            "connected_at": datetime.utcnow().isoformat(),
        }

        if integration is None:
            integration = Integration(
                project_id=project_id,
                type=IntegrationType.github,
                encrypted_credentials=json.dumps(integration_payload),
                status=IntegrationStatus.connected,
                connected_at=datetime.utcnow(),
            )
            db.add(integration)
        else:
            integration.encrypted_credentials = json.dumps(integration_payload)
            integration.status = IntegrationStatus.connected
            integration.connected_at = datetime.utcnow()

        await db.commit()

        return {"connected": True, "username": github_username}

    @staticmethod
    async def get_github_status(db: AsyncSession, project_id: str, user_id: str) -> dict:
        await ProjectService.get_project(db, project_id, user_id)
        connection = await IntegrationService._get_github_connection(db, user_id)
        if connection is None:
            return {"connected": False, "username": None, "connected_at": None}

        connected_at = connection.connected_at.isoformat() if connection.connected_at else None
        return {"connected": True, "username": connection.github_username, "connected_at": connected_at}

    @staticmethod
    async def get_github_orgs(db: AsyncSession, project_id: str, user_id: str) -> dict:
        await ProjectService.get_project(db, project_id, user_id)
        connection = await IntegrationService._get_github_connection(db, user_id)
        if connection is None:
            raise HTTPException(status_code=400, detail="GitHub is not connected")

        def _fetch_orgs(access_token: str) -> list[dict]:
            gh = Github(access_token)
            return [{"login": org.login, "id": org.id} for org in gh.get_user().get_orgs()]

        try:
            orgs = await asyncio.to_thread(_fetch_orgs, connection.encrypted_access_token)
        except GithubException as exc:
            raise HTTPException(status_code=400, detail=f"Failed to fetch GitHub orgs: {exc.data}") from exc

        return {"orgs": orgs}

    @staticmethod
    async def push_to_github(
        db: AsyncSession,
        project_id: str,
        user_id: str,
        *,
        repo_name: str,
        is_private: bool,
        branch: str,
        commit_message: str,
        owner: str | None,
    ) -> dict:
        await ProjectService.get_project(db, project_id, user_id)
        connection = await IntegrationService._get_github_connection(db, user_id)
        if connection is None:
            raise HTTPException(status_code=400, detail="Connect your GitHub account first")

        project_dir = get_project_dir(project_id)
        if not project_dir.exists() or not project_dir.is_dir():
            raise HTTPException(status_code=404, detail="Project files not found")

        try:
            result = await asyncio.to_thread(
                IntegrationService._push_repository_contents,
                access_token=connection.encrypted_access_token,
                repo_name=repo_name,
                owner=owner,
                is_private=is_private,
                branch=branch,
                commit_message=commit_message,
                project_dir=project_dir,
            )
        except GithubException as exc:
            message = exc.data.get("message") if isinstance(exc.data, dict) else str(exc)
            raise HTTPException(status_code=400, detail=f"GitHub push failed: {message}") from exc

        integration = await IntegrationService._get_integration(db, project_id, IntegrationType.github)
        payload = {
            "github_username": connection.github_username,
            "repo": f"{result['owner']}/{result['name']}",
            "url": result["url"],
            "branch": result["branch"],
            "connected_at": datetime.utcnow().isoformat(),
        }

        if integration is None:
            integration = Integration(
                project_id=project_id,
                type=IntegrationType.github,
                encrypted_credentials=json.dumps(payload),
                status=IntegrationStatus.connected,
                connected_at=datetime.utcnow(),
            )
            db.add(integration)
        else:
            integration.encrypted_credentials = json.dumps(payload)
            integration.status = IntegrationStatus.connected
            integration.connected_at = datetime.utcnow()

        await db.commit()
        return result
