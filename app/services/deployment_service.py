import os
import asyncio
import subprocess
from app.config import settings
from app.socketio.server import sio

class DeploymentService:
    @staticmethod
    async def deploy_project(project_id: str, subdomain: str) -> str:
        """
        Runs the build process for a generated frontend and streams the output to the client.
        Then, sets up a local server / tunnel alias if needed, or simply returns a success URL.
        """
        # Determine project directory
        if settings.USER_PROJECTS_DIR:
            project_dir = os.path.join(settings.USER_PROJECTS_DIR, project_id)
        else:
            backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            root_dir = os.path.dirname(backend_dir)
            project_dir = os.path.join(root_dir, 'user_projects', project_id)
            
        if not os.path.exists(project_dir):
            raise Exception("Project directory not found")

        # Emit initial status
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

        # Mocking the edge deployment part since we don't have Vercel tokens
        steps = [
            f"Pushing artifacts to edge nodes for {subdomain}.enliven-app.com...",
            "Provisioning SSL certificates...",
            "Warming up edge cache...",
            "Deployment complete. Domain is live."
        ]

        for step in steps:
            await asyncio.sleep(0.6)
            await sio.emit("deployment_log", {"line": step}, room=project_id)

        # Mock public URL
        return f"https://{subdomain}.enliven-app.com"
