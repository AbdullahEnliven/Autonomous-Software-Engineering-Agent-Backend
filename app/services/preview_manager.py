import subprocess
import os
import hashlib
import asyncio
import socket
from typing import Dict
from app.utils.paths import get_project_dir

# In-memory dictionary to track running Vite processes
# Mapping: project_id -> subprocess.Popen
ACTIVE_PREVIEWS: Dict[str, subprocess.Popen] = {}

class PreviewManager:
    @staticmethod
    def get_port(project_id: str) -> int:
        """Calculate deterministic port for a project."""
        base_hash = int(hashlib.md5(str(project_id).encode()).hexdigest(), 16)
        return 6000 + (base_hash % 3000)

    @staticmethod
    def _is_port_open(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            return sock.connect_ex(("127.0.0.1", port)) == 0

    @staticmethod
    async def start_preview(project_id: str):
        """Start the Vite dev server for a project if not already running."""
        existing = ACTIVE_PREVIEWS.get(project_id)
        if existing and existing.poll() is None:
            return existing

        # Clean up stale process handle.
        if existing and existing.poll() is not None:
            ACTIVE_PREVIEWS.pop(project_id, None)

        port = PreviewManager.get_port(project_id)
        
        target_dir = str(get_project_dir(project_id))
        
        if not os.path.exists(target_dir):
            return None  # Project doesn't exist yet
            
        print(f"[PreviewManager] Starting Vite server for {project_id} on port {port}")
        
        # Kill any existing stray process holding the port just in case
        try:
            subprocess.run(f'FOR /F "tokens=5" %a IN (\'netstat -aon ^| findstr :{port}\') DO taskkill /F /PID %a', shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        except Exception:
            pass
            
        # Spawn the vite server process. We use shell=True on Windows for npx.cmd to work reliably.
        proc = subprocess.Popen(
            f'npx.cmd vite --port {port}', 
            cwd=target_dir, 
            shell=True, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        
        ACTIVE_PREVIEWS[project_id] = proc
        return proc

    @staticmethod
    async def ensure_preview_ready(project_id: str, timeout_seconds: float = 10.0) -> bool:
        """Ensure preview process is started and localhost port is accepting connections."""
        port = PreviewManager.get_port(project_id)

        if PreviewManager._is_port_open(port):
            return True

        proc = await PreviewManager.start_preview(project_id)
        if proc is None:
            return False

        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            if proc.poll() is not None:
                # Process exited unexpectedly.
                ACTIVE_PREVIEWS.pop(project_id, None)
                return False
            if PreviewManager._is_port_open(port):
                return True
            await asyncio.sleep(0.25)

        return False

    @staticmethod
    async def stop_preview(project_id: str):
        """Stop the Vite dev server for a project."""
        proc = ACTIVE_PREVIEWS.pop(project_id, None)
        if proc:
            print(f"[PreviewManager] Stopping Vite server for {project_id}")
            try:
                # Use taskkill to aggressively kill the process tree since we used shell=True
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(proc.pid)], 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )
            except Exception as e:
                print(f"[PreviewManager] Error stopping process: {e}")
