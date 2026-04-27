import asyncio
import hashlib
import html
import shutil
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.project import Project


class ThumbnailService:
    THUMBNAIL_DIR = Path(settings.ARTIFACT_PATH) / "thumbnails"

    @staticmethod
    def thumbnail_url(project_id: str) -> str:
        return f"/api/v1/projects/{project_id}/thumbnail"

    @staticmethod
    def _base_path(project_id: str) -> Path:
        return ThumbnailService.THUMBNAIL_DIR / str(project_id)

    @staticmethod
    def existing_thumbnail_path(project_id: str) -> Path | None:
        base = ThumbnailService._base_path(project_id)
        for suffix in (".png", ".svg"):
            candidate = base.with_suffix(suffix)
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    @staticmethod
    def ensure_thumbnail_url(project: Project) -> bool:
        url = ThumbnailService.thumbnail_url(str(project.id))
        if project.thumbnail_url == url:
            return False
        project.thumbnail_url = url
        return True

    @staticmethod
    def _accent_for_project(project: Project) -> str:
        palette = ["#2563eb", "#0f766e", "#7c3aed", "#be123c", "#ca8a04", "#0891b2"]
        digest = hashlib.sha256(str(project.id).encode("utf-8")).hexdigest()
        return palette[int(digest[:2], 16) % len(palette)]

    @staticmethod
    def _write_placeholder(project: Project) -> Path:
        ThumbnailService.THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
        path = ThumbnailService._base_path(str(project.id)).with_suffix(".svg")
        safe_name = html.escape(project.name or "Untitled Store")
        accent = ThumbnailService._accent_for_project(project)
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#111827"/>
      <stop offset="1" stop-color="#050505"/>
    </linearGradient>
    <linearGradient id="wash" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{accent}" stop-opacity="0.35"/>
      <stop offset="1" stop-color="#ffffff" stop-opacity="0.06"/>
    </linearGradient>
  </defs>
  <rect width="1280" height="720" fill="url(#bg)"/>
  <rect x="72" y="72" width="1136" height="576" rx="36" fill="#0b0b0d" stroke="#2a2a2a" stroke-width="2"/>
  <rect x="72" y="72" width="1136" height="170" rx="36" fill="url(#wash)"/>
  <circle cx="116" cy="116" r="10" fill="#ef4444"/>
  <circle cx="148" cy="116" r="10" fill="#f59e0b"/>
  <circle cx="180" cy="116" r="10" fill="#22c55e"/>
  <rect x="234" y="100" width="812" height="32" rx="16" fill="#ffffff" opacity="0.08"/>
  <text x="112" y="396" fill="#ffffff" font-family="Inter, Arial, sans-serif" font-size="76" font-weight="800">{safe_name}</text>
  <text x="116" y="460" fill="#a3a3a3" font-family="Inter, Arial, sans-serif" font-size="30">Store thumbnail</text>
  <rect x="112" y="516" width="220" height="52" rx="26" fill="{accent}"/>
  <text x="154" y="551" fill="#ffffff" font-family="Inter, Arial, sans-serif" font-size="22" font-weight="700">ASEA Store</text>
</svg>"""
        path.write_text(svg, encoding="utf-8")
        return path

    @staticmethod
    async def _try_capture_screenshot(source_url: str, output_path: Path) -> bool:
        if not source_url.startswith(("http://", "https://")):
            return False

        if await ThumbnailService._try_capture_with_chrome(source_url, output_path):
            return True

        try:
            from playwright.async_api import async_playwright
        except Exception:
            return False

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
                await page.goto(source_url, wait_until="networkidle", timeout=30000)
                await page.screenshot(path=str(output_path), type="png", full_page=False)
                await browser.close()
            return True
        except Exception:
            return False

    @staticmethod
    def _find_chrome_binary() -> str | None:
        candidates = [
            shutil.which("chrome"),
            shutil.which("chrome.exe"),
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            shutil.which("msedge"),
            shutil.which("msedge.exe"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return str(candidate)
        return None

    @staticmethod
    async def _try_capture_with_chrome(source_url: str, output_path: Path) -> bool:
        chrome = ThumbnailService._find_chrome_binary()
        if not chrome:
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="asea_chrome_") as user_data_dir:
            cmd = [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={user_data_dir}",
                "--window-size=1280,720",
                f"--screenshot={output_path}",
                source_url,
            ]
            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
            except Exception:
                return False

        return result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0

    @staticmethod
    async def ensure_thumbnail(
        db: AsyncSession,
        project: Project,
        source_url: str | None = None,
        refresh: bool = False,
    ) -> Path:
        ThumbnailService.ensure_thumbnail_url(project)

        existing = ThumbnailService.existing_thumbnail_path(str(project.id))
        if existing and not refresh and (not source_url or existing.suffix.lower() == ".png"):
            return existing

        png_path = ThumbnailService._base_path(str(project.id)).with_suffix(".png")
        if source_url and await ThumbnailService._try_capture_screenshot(source_url, png_path):
            svg_path = ThumbnailService._base_path(str(project.id)).with_suffix(".svg")
            if svg_path.exists():
                svg_path.unlink()
            return png_path

        return ThumbnailService._write_placeholder(project)

    @staticmethod
    async def generate_for_projects(
        db: AsyncSession,
        projects: list[Project],
        source_urls_by_project_id: dict,
        refresh: bool = False,
    ) -> None:
        for project in projects:
            await ThumbnailService.ensure_thumbnail(
                db,
                project,
                source_urls_by_project_id.get(project.id),
                refresh=refresh,
            )
        await db.commit()
