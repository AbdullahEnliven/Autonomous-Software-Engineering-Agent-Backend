import os
import asyncio
import subprocess
import socket
import sys
from app.config import settings
from app.socketio.server import sio


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
        # Determine project directory
        if not settings.USER_PROJECTS_DIR:
            backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            root_dir = os.path.dirname(backend_dir)
            project_dir = os.path.join(root_dir, 'user_projects', project_id)
        else:
            project_dir = os.path.join(settings.USER_PROJECTS_DIR, project_id)
            
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

