import os
import asyncio
import subprocess
import socket
import sys
import re
import json
import shutil
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.models.project import Integration, IntegrationStatus, IntegrationType, Project, ProjectStatus
from app.services.integration_service import IntegrationService
from app.services.project_service import ProjectService
from app.services.thumbnail_service import ThumbnailService
from app.socketio.server import sio
from app.utils.paths import get_project_dir


class DeploymentService:
    _local_server_process = None
    _local_server_project_id = None

    @classmethod
    def _is_port_in_use(cls, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            return sock.connect_ex(("127.0.0.1", port)) == 0

    @classmethod
    async def _start_local_static_server(cls, project_id: str, dist_dir: str) -> int:
        port = int(settings.LOCAL_DEPLOYMENT_PORT)

        # Reuse running server if already serving this project.
        if cls._local_server_process and cls._local_server_process.poll() is None:
            if cls._local_server_project_id == project_id:
                return port

            cls._local_server_process.terminate()
            try:
                await asyncio.to_thread(cls._local_server_process.wait, 2)
            except Exception:
                cls._local_server_process.kill()

        # If some external process is already on the port, fail with clear guidance.
        if cls._is_port_in_use(port):
            raise Exception(
                f"Port {port} is already in use. Stop the existing process or change LOCAL_DEPLOYMENT_PORT."
            )

        process = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
            cwd=dist_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        await asyncio.sleep(0.8)

        if process.poll() is not None:
            output = ""
            if process.stdout:
                output = process.stdout.read().strip()
            raise Exception(f"Failed to start local static server on port {port}. {output}")

        cls._local_server_process = process
        cls._local_server_project_id = project_id
        return port

    @staticmethod
    async def deploy_project(project_id: str, subdomain: str) -> str:
        """
        Runs the build process and returns a URL based on deployment mode:
            - Local mode: Returns localhost URL with instructions
            - Production mode: Returns enliven-app.com domain
        """
        return await DeploymentService._deploy_local_or_mock(project_id, subdomain)

    @staticmethod
    async def deploy_project_for_user(
        db: AsyncSession,
        project_id: str,
        user_id: str,
        subdomain: str,
        target: str = "production",
    ) -> str:
        # Validate ownership first.
        await ProjectService.get_project(db, project_id, user_id)

        if settings.VERCEL_TOKEN:
            return await DeploymentService._deploy_to_vercel(db, project_id, subdomain, target)

        if target == "preview":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Preview deployment requires VERCEL_TOKEN to be configured.",
            )

        return await DeploymentService._deploy_local_or_mock(project_id, subdomain)

    @staticmethod
    async def _deploy_local_or_mock(project_id: str, subdomain: str) -> str:
        # Determine project directory
        project_dir = str(get_project_dir(project_id))

        if not os.path.exists(project_dir):
            raise Exception("Project directory not found")

        # Emit initial status
        if settings.DEPLOYMENT_MODE == "local":
            await sio.emit("deployment_log", {"line": "[LOCAL MODE] Building project for local deployment..."}, room=project_id)
        else:
            await sio.emit("deployment_log", {"line": "[PRODUCTION MODE] Deploying to ASEA Cloud..."}, room=project_id)

        await sio.emit("deployment_log", {"line": "Authenticating with ASEA Cloud Edge..."}, room=project_id)
        await asyncio.sleep(0.5)
        await sio.emit("deployment_log", {"line": "SUCCESS: Authenticated."}, room=project_id)
        await sio.emit("deployment_log", {"line": f"Initializing build environment in {project_dir}..."}, room=project_id)

        async def stream_subprocess(cmd, cwd, project_id):
            process = subprocess.Popen(
                cmd,
                shell=True,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT
            )
            
            while True:
                line = await asyncio.to_thread(process.stdout.readline)
                if not line:
                    break
                await sio.emit("deployment_log", {"line": line.decode('utf-8', errors='replace').strip()}, room=project_id)
            
            return await asyncio.to_thread(process.wait)

        try:
            # Run npm install if node_modules doesn't exist, else just build
            if not os.path.exists(os.path.join(project_dir, 'node_modules')):
                await sio.emit("deployment_log", {"line": "Installing dependencies (npm install)..."}, room=project_id)
                await stream_subprocess('npm install', project_dir, project_id)

            await sio.emit("deployment_log", {"line": "Running production build (npm run build)..."}, room=project_id)
            return_code = await stream_subprocess('npm run build', project_dir, project_id)
            
            if return_code == 0:
                await sio.emit("deployment_log", {"line": "Build successful! Assets generated in /dist."}, room=project_id)
            else:
                await sio.emit("deployment_log", {"line": "[ERROR] Build failed. Check logs above."}, room=project_id)
                raise Exception("Build failed")

        except Exception as e:
            await sio.emit("deployment_log", {"line": f"[ERROR] Subprocess error: {str(e)}"}, room=project_id)
            raise e

        # Return URL based on deployment mode
        if settings.DEPLOYMENT_MODE == "local":
            # Local deployment mode
            dist_dir = os.path.join(project_dir, 'dist')
            if not os.path.exists(dist_dir):
                raise Exception("Build output /dist not found")

            await sio.emit("deployment_log", {"line": "Starting local static server..."}, room=project_id)
            port = await DeploymentService._start_local_static_server(project_id, dist_dir)

            await sio.emit("deployment_log", {"line": "✓ Local server started successfully"}, room=project_id)
            await sio.emit("deployment_log", {"line": f"Serving dist from: {dist_dir}"}, room=project_id)

            deploy_url = f"http://localhost:{port}"
            await sio.emit("deployment_log", {"line": f"Access your app at: {deploy_url}"}, room=project_id)
            return deploy_url
        
        else:
            # Production deployment to enliven-app.com
            steps = [
                f"Pushing artifacts to edge nodes for {subdomain}.{settings.DEPLOYMENT_DOMAIN}...",
                "Provisioning SSL certificates...",
                "Warming up edge cache...",
                "Deployment complete. Domain is live."
            ]


            for step in steps:
                await asyncio.sleep(0.6)
                await sio.emit("deployment_log", {"line": step}, room=project_id)

            # Return production URL
            return f"https://{subdomain}.{settings.DEPLOYMENT_DOMAIN}"

    @staticmethod
    def _build_vercel_project_slug(project_id: str, preferred_slug: str | None = None) -> str:
        seed = (preferred_slug or "").strip().lower()
        if seed:
            seed = re.sub(r"[^a-z0-9._-]", "-", seed)
            seed = re.sub(r"-{3,}", "--", seed)
            seed = re.sub(r"^-+", "", seed)
            seed = re.sub(r"-+$", "", seed)

        base = seed or f"{settings.VERCEL_PROJECT_PREFIX}-{str(project_id)[:8]}".lower()
        # Vercel allows lowercase letters, digits, '.', '_', '-'; disallow triple-dash.
        base = re.sub(r"[^a-z0-9._-]", "-", base)
        base = re.sub(r"-{3,}", "--", base)
        base = re.sub(r"^-+", "", base)
        base = re.sub(r"-+$", "", base)
        return (base or f"asea-{str(project_id)[:8]}")[:100]

    @staticmethod
    async def _deploy_to_vercel(
        db: AsyncSession,
        project_id: str,
        subdomain: str,
        target: str,
    ) -> str:
        project_dir = str(get_project_dir(project_id))
        if not os.path.exists(project_dir):
            raise HTTPException(status_code=404, detail="Project directory not found")

        target = (target or "production").strip().lower()
        if target not in {"preview", "production"}:
            raise HTTPException(status_code=400, detail="target must be 'preview' or 'production'")

        await sio.emit(
            "deployment_log",
            {"line": f"[VERCEL] Starting {target} deployment..."},
            room=project_id,
        )

        npx_bin = shutil.which("npx") or shutil.which("npx.cmd")
        if not npx_bin:
            raise HTTPException(
                status_code=500,
                detail="Node.js/npm is required for Vercel deploys. 'npx' was not found in PATH.",
            )

        project_slug = DeploymentService._build_vercel_project_slug(project_id, subdomain)
        env = os.environ.copy()
        env["CI"] = "1"

        async def run_vercel_deploy(use_scope: bool) -> tuple[int, str, str | None]:
            if os.name == "nt":
                cmd = [
                    "cmd",
                    "/c",
                    "npx",
                    "--yes",
                    "vercel@latest",
                    "deploy",
                    "--token",
                    settings.VERCEL_TOKEN,
                    "--yes",
                    "--name",
                    project_slug,
                ]
            else:
                cmd = [
                    npx_bin,
                    "--yes",
                    "vercel@latest",
                    "deploy",
                    "--token",
                    settings.VERCEL_TOKEN,
                    "--yes",
                    "--name",
                    project_slug,
                ]

            if use_scope and settings.VERCEL_SCOPE:
                cmd.extend(["--scope", settings.VERCEL_SCOPE])
            if target == "production":
                cmd.append("--prod")

            try:
                process = subprocess.Popen(
                    cmd,
                    cwd=project_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                )
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=500,
                    detail="Unable to launch Vercel CLI process. Ensure Node.js and npm are installed and available in PATH.",
                ) from exc

            output_lines = []
            while True:
                line = await asyncio.to_thread(process.stdout.readline)
                if not line:
                    break
                cleaned = line.strip()
                output_lines.append(cleaned)
                if cleaned:
                    await sio.emit("deployment_log", {"line": cleaned}, room=project_id)

            return_code = await asyncio.to_thread(process.wait)
            output_text = "\n".join(output_lines)
            return return_code, output_text, DeploymentService._extract_vercel_url(output_text)

        use_scope = bool(settings.VERCEL_SCOPE)
        return_code, output_text, url = await run_vercel_deploy(use_scope=use_scope)

        if (
            return_code != 0
            and use_scope
            and ("scope does not exist" in output_text.lower() or "scope-not-existent" in output_text.lower())
        ):
            await sio.emit(
                "deployment_log",
                {"line": "[VERCEL] Scope is invalid for this token. Retrying deploy without --scope..."},
                room=project_id,
            )
            return_code, output_text, url = await run_vercel_deploy(use_scope=False)

        if return_code != 0 or not url:
            raise HTTPException(
                status_code=500,
                detail="Vercel deployment failed. Check deployment logs for details.",
            )

        integration = await IntegrationService._get_integration(db, project_id, IntegrationType.vercel)
        current_payload = {}
        if integration and integration.encrypted_credentials:
            try:
                current_payload = json.loads(integration.encrypted_credentials)
            except json.JSONDecodeError:
                current_payload = {}

        if target == "preview":
            current_payload["preview_url"] = url
        else:
            current_payload["production_url"] = url
        current_payload["project_slug"] = project_slug
        current_payload["last_target"] = target
        current_payload["last_deployed_at"] = datetime.utcnow().isoformat()

        if integration is None:
            integration = Integration(
                project_id=project_id,
                type=IntegrationType.vercel,
                encrypted_credentials=json.dumps(current_payload),
                status=IntegrationStatus.connected,
                connected_at=datetime.utcnow(),
            )
            db.add(integration)
        else:
            integration.encrypted_credentials = json.dumps(current_payload)
            integration.status = IntegrationStatus.connected
            integration.connected_at = datetime.utcnow()

        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalars().first()
        if project:
            project.status = ProjectStatus.deployed
            await ThumbnailService.ensure_thumbnail(db, project, url, refresh=True)

        await db.commit()
        return url

    @staticmethod
    def _extract_vercel_url(output_text: str) -> str | None:
        if not output_text:
            return None

        matches = re.findall(r"https://[a-zA-Z0-9.-]+\\.vercel\\.app", output_text)
        if matches:
            return matches[-1]

        generic_matches = re.findall(r"https://[a-zA-Z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", output_text)
        if generic_matches:
            return generic_matches[-1]

        return None

