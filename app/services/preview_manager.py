import asyncio
import hashlib
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

from app.utils.paths import get_project_dir


@dataclass
class PreviewRuntime:
    project_id: str
    port: int
    process: subprocess.Popen
    viewers: Set[str] = field(default_factory=set)
    last_touched: float = field(default_factory=time.monotonic)


class PreviewManager:
    """Manages isolated Vite preview runtimes per project."""

    _active_previews: Dict[str, PreviewRuntime] = {}
    _lock: asyncio.Lock = asyncio.Lock()
    IDLE_TTL_SECONDS = 90

    @staticmethod
    def get_port(project_id: str) -> int:
        """Calculate deterministic port for a project."""
        base_hash = int(hashlib.md5(str(project_id).encode()).hexdigest(), 16)
        return 6000 + (base_hash % 3000)

    @classmethod
    def _is_process_alive(cls, proc: Optional[subprocess.Popen]) -> bool:
        return proc is not None and proc.poll() is None

    @classmethod
    async def register_viewer(cls, project_id: str, sid: str):
        """Track a connected socket client watching a project preview."""
        async with cls._lock:
            runtime = cls._active_previews.get(project_id)
            if runtime:
                runtime.viewers.add(sid)
                runtime.last_touched = time.monotonic()

    @classmethod
    async def unregister_viewer(cls, project_id: str, sid: str) -> int:
        """Untrack a connected socket client. Returns remaining viewer count."""
        async with cls._lock:
            runtime = cls._active_previews.get(project_id)
            if not runtime:
                return 0
            runtime.viewers.discard(sid)
            runtime.last_touched = time.monotonic()
            return len(runtime.viewers)

    @classmethod
    async def start_preview(cls, project_id: str):
        """Start a Vite dev server for a project, or reuse an existing healthy one."""
        async with cls._lock:
            runtime = cls._active_previews.get(project_id)
            if runtime and cls._is_process_alive(runtime.process):
                runtime.last_touched = time.monotonic()
                return runtime.process

            port = cls.get_port(project_id)
            target_dir = str(get_project_dir(project_id))

            if not os.path.exists(target_dir):
                return None

            print(f"[PreviewManager] Starting Vite server for {project_id} on port {port}")

            # Kill any existing stray process holding the port just in case.
            try:
                subprocess.run(
                    f'FOR /F "tokens=5" %a IN (\'netstat -aon ^| findstr :{port}\') DO taskkill /F /PID %a',
                    shell=True,
                    stderr=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                )
            except Exception:
                pass

            proc = subprocess.Popen(
                f"npx.cmd vite --host 127.0.0.1 --strictPort --port {port}",
                cwd=target_dir,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            viewers = runtime.viewers if runtime else set()
            cls._active_previews[project_id] = PreviewRuntime(
                project_id=project_id,
                port=port,
                process=proc,
                viewers=viewers,
            )
            return proc

    @classmethod
    async def ensure_preview_ready(cls, project_id: str, timeout_seconds: float = 5.0) -> bool:
        """Ensure the project preview process is running and accepting TCP connections."""
        await cls.start_preview(project_id)

        port = cls.get_port(project_id)
        deadline = time.monotonic() + max(timeout_seconds, 0.0)

        while time.monotonic() < deadline:
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                await writer.wait_closed()
                return True
            except Exception:
                await asyncio.sleep(0.15)

        return False

    @classmethod
    async def touch_project(cls, project_id: str):
        """Mark project runtime as recently active."""
        async with cls._lock:
            runtime = cls._active_previews.get(project_id)
            if runtime:
                runtime.last_touched = time.monotonic()

    @classmethod
    async def restart_preview(cls, project_id: str):
        """Restart an active project preview so Vite serves the current working tree."""
        async with cls._lock:
            runtime = cls._active_previews.pop(project_id, None)
            viewers = set(runtime.viewers) if runtime else set()

        if runtime and cls._is_process_alive(runtime.process):
            print(f"[PreviewManager] Restarting Vite server for {project_id}")
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(runtime.process.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                print(f"[PreviewManager] Error stopping process for restart: {e}")

        proc = await cls.start_preview(project_id)
        async with cls._lock:
            restarted = cls._active_previews.get(project_id)
            if restarted:
                restarted.viewers.update(viewers)
                restarted.last_touched = time.monotonic()
        return proc

    @classmethod
    async def stop_preview(cls, project_id: str):
        """Stop the Vite dev server for a project."""
        async with cls._lock:
            runtime = cls._active_previews.pop(project_id, None)

        if runtime and cls._is_process_alive(runtime.process):
            print(f"[PreviewManager] Stopping Vite server for {project_id}")
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(runtime.process.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                print(f"[PreviewManager] Error stopping process: {e}")

    @classmethod
    async def stop_if_idle(cls, project_id: str):
        """Stop preview if no viewers are attached and TTL has elapsed."""
        async with cls._lock:
            runtime = cls._active_previews.get(project_id)
            if not runtime:
                return

            idle_for = time.monotonic() - runtime.last_touched
            if runtime.viewers or idle_for < cls.IDLE_TTL_SECONDS:
                return

        await cls.stop_preview(project_id)
