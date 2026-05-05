"""
preview_manager.py
------------------
Vercel-based preview system.

Strategy
~~~~~~~~
* When a user opens the builder we check whether we already have a fresh
  Vercel preview URL for this project (stored in the DB Integration row).
* A "fresh" URL means the project file-tree hash hasn't changed since the
  last preview deploy.
* If stale (or no URL yet) we kick off an async background deploy to Vercel
  using `vercel deploy` (no --prod flag → preview environment).
* The deploy result is stored in the DB integration row so the next request
  immediately returns the URL without re-deploying.
* On "Deploy to production" we check: if the preview hash matches the current
  code hash we just re-alias/use the existing preview URL by running
  `vercel --prod` pointing at the same project slug — Vercel re-uses the
  cached build, making it fast. Otherwise a normal full production deploy runs.

Socket events emitted
~~~~~~~~~~~~~~~~~~~~~
  preview_status  { status: "idle"|"deploying"|"ready"|"error",
                    url: str|null,
                    message: str }
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from app.utils.paths import get_project_dir


# ---------------------------------------------------------------------------
# In-memory cache (survives for the life of the worker process)
# ---------------------------------------------------------------------------

@dataclass
class PreviewState:
    status: str = "idle"          # idle | deploying | ready | error
    url: Optional[str] = None
    file_hash: Optional[str] = None
    message: str = ""
    deploy_task: Optional[asyncio.Task] = None

_preview_cache: Dict[str, PreviewState] = {}
_cache_lock: asyncio.Lock = asyncio.Lock()


def _get_state(project_id: str) -> PreviewState:
    return _preview_cache.setdefault(project_id, PreviewState())


# ---------------------------------------------------------------------------
# File hashing
# ---------------------------------------------------------------------------

IGNORED = {".git", "node_modules", "dist", "build", "__pycache__", ".vercel"}


def compute_project_hash(project_id: str) -> str:
    """Return a stable SHA-256 of every source file in the project directory."""
    project_dir = str(get_project_dir(project_id))
    if not os.path.exists(project_dir):
        return ""

    h = hashlib.sha256()
    for root, dirs, files in os.walk(project_dir):
        # Prune ignored dirs in-place so os.walk won't descend into them
        dirs[:] = sorted(d for d in dirs if d not in IGNORED)
        for fname in sorted(files):
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, project_dir)
            h.update(rel.encode())
            try:
                with open(fpath, "rb") as f:
                    while chunk := f.read(65536):
                        h.update(chunk)
            except OSError:
                pass
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Vercel deploy helper (async, streams logs via SocketIO)
# ---------------------------------------------------------------------------

async def _run_vercel_preview(
    project_id: str,
    project_dir: str,
    project_slug: str,
    vercel_token: str,
    vercel_scope: str,
    sio,
) -> Optional[str]:
    """Run `vercel deploy` (preview) and return the resulting URL or None."""

    # ── Patch vercel.json to allow iframing ──────────────────────────────
    # Vercel adds X-Frame-Options: SAMEORIGIN by default which blocks our
    # builder iframe. We merge headers into the project's vercel.json.
    vercel_json_path = os.path.join(project_dir, "vercel.json")
    try:
        config: dict = {}
        if os.path.exists(vercel_json_path):
            with open(vercel_json_path, "r", encoding="utf-8") as f:
                config = json.load(f)

        frame_headers = [
            {"key": "X-Frame-Options", "value": "ALLOWALL"},
            {"key": "Content-Security-Policy", "value": "frame-ancestors *"},
        ]

        existing_headers: list = config.get("headers", [])
        # Find an existing catch-all rule or add one
        wildcard = next(
            (h for h in existing_headers if h.get("source") in ["/(.*)", "**", "/*"]),
            None,
        )
        if wildcard:
            existing_keys = {h["key"] for h in wildcard.get("headers", [])}
            for fh in frame_headers:
                if fh["key"] not in existing_keys:
                    wildcard.setdefault("headers", []).append(fh)
        else:
            existing_headers.append({"source": "/(.*)", "headers": frame_headers})

        config["headers"] = existing_headers
        with open(vercel_json_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print(f"[PreviewManager] Patched vercel.json for iframe embedding in {project_dir}")
    except Exception as exc:
        print(f"[PreviewManager] Warning: could not patch vercel.json: {exc}")
    # ─────────────────────────────────────────────────────────────────────

    npx_bin = shutil.which("npx") or shutil.which("npx.cmd") or "npx"

    if os.name == "nt":
        cmd = ["cmd", "/c", "npx", "--yes", "vercel@latest", "deploy",
               "--token", vercel_token, "--yes", "--name", project_slug]
    else:
        cmd = [npx_bin, "--yes", "vercel@latest", "deploy",
               "--token", vercel_token, "--yes", "--name", project_slug]

    if vercel_scope:
        cmd += ["--scope", vercel_scope]

    env = os.environ.copy()
    env["CI"] = "1"

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        return None

    output_lines: list[str] = []
    while True:
        line = await asyncio.to_thread(proc.stdout.readline)
        if not line:
            break
        cleaned = line.strip()
        if cleaned:
            output_lines.append(cleaned)
            if sio:
                try:
                    await sio.emit(
                        "preview_status",
                        {"status": "deploying", "url": None, "message": cleaned},
                        room=project_id,
                    )
                except Exception:
                    pass

    rc = await asyncio.to_thread(proc.wait)
    full_output = "\n".join(output_lines)

    if rc != 0:
        return None

    # Extract the Vercel URL from output
    import re
    matches = re.findall(r"https://[a-zA-Z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", full_output)
    if not matches:
        return None

    # Return the last https URL that looks like a Vercel preview URL
    vercel_urls = [u for u in matches if "vercel.app" in u]
    return vercel_urls[-1] if vercel_urls else matches[-1]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class PreviewManager:
    """
    Vercel-based preview manager.  Drop-in replacement for the old Vite manager.
    All public methods are safe to call from async FastAPI/SocketIO handlers.
    """

    # ---- Compatibility stubs (called from socketio/server.py) -----------

    @classmethod
    async def register_viewer(cls, project_id: str, sid: str):
        """No-op — Vercel previews don't need viewer tracking."""

    @classmethod
    async def unregister_viewer(cls, project_id: str, sid: str) -> int:
        """No-op — returns 0."""
        return 0

    @classmethod
    async def stop_if_idle(cls, project_id: str):
        """No-op — Vercel previews are persistent, nothing to stop."""

    @classmethod
    async def start_preview(cls, project_id: str):
        """No-op — preview is triggered via trigger_preview() / get_status()."""

    # ---- Real implementation --------------------------------------------

    @classmethod
    def get_status(cls, project_id: str) -> dict:
        """Return the current in-memory preview state as a plain dict."""
        async def _sync():
            pass
        state = _preview_cache.get(project_id, PreviewState())
        return {
            "status": state.status,
            "url": state.url,
            "message": state.message,
            "file_hash": state.file_hash,
        }

    @classmethod
    async def get_or_create_preview(
        cls,
        project_id: str,
        vercel_token: str,
        vercel_scope: str,
        project_slug: str,
        sio=None,
        db=None,
        stored_url: Optional[str] = None,
        stored_hash: Optional[str] = None,
    ) -> dict:
        """
        Main entry point.
        1. Compute current file hash.
        2. If hash matches stored hash and URL exists → return cached URL.
        3. Otherwise trigger a background Vercel deploy (non-blocking).
        Returns a status dict immediately.
        """
        async with _cache_lock:
            state = _get_state(project_id)

            current_hash = compute_project_hash(project_id)

            # Already deploying — just return current state
            if state.status == "deploying":
                return cls.get_status(project_id)

            # Check in-memory cache first
            if state.status == "ready" and state.url and state.file_hash == current_hash:
                return cls.get_status(project_id)

            # Check DB-persisted URL (passed in by the router)
            if stored_url and stored_hash and stored_hash == current_hash:
                state.status = "ready"
                state.url = stored_url
                state.file_hash = current_hash
                state.message = "Preview ready (cached)"
                return cls.get_status(project_id)

            # Need a new deploy
            if not vercel_token:
                state.status = "error"
                state.message = "VERCEL_TOKEN not configured. Cannot build preview."
                return cls.get_status(project_id)

            project_dir = str(get_project_dir(project_id))
            if not os.path.exists(project_dir):
                state.status = "error"
                state.message = "Project directory not found."
                return cls.get_status(project_id)

            # Mark deploying and launch background task
            state.status = "deploying"
            state.message = "Starting Vercel preview deploy…"
            state.file_hash = current_hash  # track hash we're deploying

            # Fire-and-forget background task
            task = asyncio.create_task(
                cls._background_deploy(
                    project_id=project_id,
                    project_dir=project_dir,
                    project_slug=project_slug,
                    vercel_token=vercel_token,
                    vercel_scope=vercel_scope,
                    expected_hash=current_hash,
                    sio=sio,
                    db=db,
                )
            )
            state.deploy_task = task

            return cls.get_status(project_id)

    @classmethod
    async def _background_deploy(
        cls,
        project_id: str,
        project_dir: str,
        project_slug: str,
        vercel_token: str,
        vercel_scope: str,
        expected_hash: str,
        sio,
        db,
    ):
        """Runs in background; updates state and emits socket events."""
        try:
            url = await _run_vercel_preview(
                project_id=project_id,
                project_dir=project_dir,
                project_slug=project_slug,
                vercel_token=vercel_token,
                vercel_scope=vercel_scope,
                sio=sio,
            )

            async with _cache_lock:
                state = _get_state(project_id)

                if url:
                    state.status = "ready"
                    state.url = url
                    state.file_hash = expected_hash
                    state.message = "Preview ready"

                    # Persist URL + hash to DB integration row
                    if db is not None:
                        try:
                            await cls._persist_preview_url(
                                db, project_id, url, expected_hash, project_slug
                            )
                        except Exception as exc:
                            print(f"[PreviewManager] DB persist error: {exc}")
                else:
                    state.status = "error"
                    state.message = "Vercel preview deploy failed. Check project for build errors."

            if sio:
                await sio.emit(
                    "preview_status",
                    cls.get_status(project_id),
                    room=project_id,
                )

        except Exception as exc:
            print(f"[PreviewManager] Background deploy error: {exc}")
            async with _cache_lock:
                state = _get_state(project_id)
                state.status = "error"
                state.message = str(exc)
            if sio:
                try:
                    await sio.emit("preview_status", cls.get_status(project_id), room=project_id)
                except Exception:
                    pass

    @classmethod
    async def _persist_preview_url(cls, db, project_id: str, url: str, file_hash: str, project_slug: str):
        """Save preview URL + hash to the Vercel Integration DB row."""
        from app.models.project import Integration, IntegrationStatus, IntegrationType
        from sqlalchemy.future import select

        result = await db.execute(
            select(Integration).where(
                Integration.project_id == project_id,
                Integration.type == IntegrationType.vercel,
            )
        )
        integration = result.scalars().first()
        payload: dict = {}
        if integration and integration.encrypted_credentials:
            try:
                payload = json.loads(integration.encrypted_credentials)
            except json.JSONDecodeError:
                payload = {}

        payload["preview_url"] = url
        payload["preview_file_hash"] = file_hash
        payload["project_slug"] = project_slug
        payload["last_preview_at"] = datetime.now(timezone.utc).isoformat()

        if integration is None:
            from app.models.project import Integration
            integration = Integration(
                project_id=project_id,
                type=IntegrationType.vercel,
                encrypted_credentials=json.dumps(payload),
                status=IntegrationStatus.connected,
                connected_at=datetime.now(timezone.utc),
            )
            db.add(integration)
        else:
            integration.encrypted_credentials = json.dumps(payload)
            integration.status = IntegrationStatus.connected
            integration.connected_at = datetime.now(timezone.utc)

        await db.commit()

    @classmethod
    async def invalidate(cls, project_id: str):
        """
        Called after code changes (chat edit, file save, checkpoint restore).
        Clears the cached hash so the next preview request triggers a redeploy.
        Does NOT immediately redeploy — we wait for the user to look at the preview.
        """
        async with _cache_lock:
            state = _get_state(project_id)
            # Only reset if currently ready; keep "deploying" state intact
            if state.status == "ready":
                state.status = "idle"
                state.file_hash = None
                state.message = "Code changed — preview will redeploy on next view"

    @classmethod
    async def restart_preview(cls, project_id: str):
        """
        Compatibility alias used by socketio/server.py after agent edits.
        Simply invalidates so the next preview load triggers a fresh deploy.
        """
        await cls.invalidate(project_id)

    # ---- Port stubs (not used but may be imported elsewhere) -------------

    @staticmethod
    def get_port(project_id: str) -> int:
        """Not used — returns 0 as placeholder."""
        return 0
