import json
from datetime import datetime

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.project import Integration, IntegrationStatus, IntegrationType
from app.schemas.integration import SupabaseCredentials
from app.services.project_service import ProjectService


class IntegrationService:
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
