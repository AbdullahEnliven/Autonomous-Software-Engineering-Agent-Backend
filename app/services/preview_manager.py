import subprocess
import os
import hashlib
from typing import Dict
from app.config import settings

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
    async def start_preview(project_id: str):
        """Start the Vite dev server for a project if not already running."""
        if project_id in ACTIVE_PREVIEWS:
            # Process is already registered as running
            return
            
        port = PreviewManager.get_port(project_id)
        target_dir = os.path.join(settings.USER_PROJECTS_DIR, project_id)
        
        if not os.path.exists(target_dir):
            return # Project doesn't exist yet
            
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
