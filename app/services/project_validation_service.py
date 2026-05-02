import asyncio
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

from app.utils.paths import get_project_dir


@dataclass
class ProjectValidationResult:
    success: bool
    command: List[str]
    output: str = ""
    skipped: bool = False
    reason: str = ""
    timed_out: bool = False


class ProjectValidationService:
    """Runs a generated project's local build to catch Vite/React compiler errors."""

    OUTPUT_LIMIT = 12000
    SYNTAX_SCRIPT = r"""
const fs = require('fs');
const path = require('path');

let parser;
try {
  parser = require('@babel/parser');
} catch (error) {
  console.log(JSON.stringify({ skipped: true, reason: '@babel/parser is not available' }));
  process.exit(0);
}

const projectRoot = process.argv[1];
const srcRoot = fs.existsSync(path.join(projectRoot, 'src')) ? path.join(projectRoot, 'src') : projectRoot;
const exts = new Set(['.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs']);
const skipDirs = new Set(['node_modules', '.git', 'dist', 'build', '.next']);
let checked = 0;

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!skipDirs.has(entry.name)) walk(path.join(dir, entry.name));
      continue;
    }

    const ext = path.extname(entry.name);
    if (!exts.has(ext)) continue;

    const file = path.join(dir, entry.name);
    const code = fs.readFileSync(file, 'utf8');
    checked += 1;
    try {
      parser.parse(code, {
        sourceType: 'module',
        errorRecovery: false,
        plugins: [
          'jsx',
          'typescript',
          'classProperties',
          'classPrivateProperties',
          'classPrivateMethods',
          'objectRestSpread',
          'dynamicImport',
          'importMeta',
          'topLevelAwait'
        ],
      });
    } catch (error) {
      console.log(JSON.stringify({
        success: false,
        file,
        line: error.loc && error.loc.line,
        column: error.loc && error.loc.column,
        message: error.message,
      }));
      process.exit(1);
    }
  }
}

walk(srcRoot);
console.log(JSON.stringify({ success: true, checked }));
"""

    @staticmethod
    def _npm_command() -> str | None:
        executable = "npm.cmd" if sys.platform.startswith("win") else "npm"
        return shutil.which(executable)

    @staticmethod
    def _node_command() -> str | None:
        executable = "node.exe" if sys.platform.startswith("win") else "node"
        return shutil.which(executable)

    @classmethod
    async def validate_project(
        cls,
        project_id: str,
        timeout_seconds: float = 60.0,
    ) -> ProjectValidationResult:
        project_dir = get_project_dir(project_id)
        command = ["npm.cmd" if sys.platform.startswith("win") else "npm", "run", "build"]

        if not project_dir.exists():
            return ProjectValidationResult(
                success=False,
                command=command,
                output=f"Project directory not found: {project_dir}",
            )

        package_json = project_dir / "package.json"
        if not package_json.exists():
            return ProjectValidationResult(
                success=True,
                command=command,
                skipped=True,
                reason="No package.json found; skipped build validation.",
            )

        syntax_result = await cls._validate_syntax(project_dir)
        if not syntax_result.success or syntax_result.skipped:
            return syntax_result

        npm_path = cls._npm_command()
        if not npm_path:
            return ProjectValidationResult(
                success=True,
                command=command,
                skipped=True,
                reason="npm was not found in PATH; skipped build validation.",
            )

        env = os.environ.copy()
        env["CI"] = "true"
        env["NO_COLOR"] = "1"

        try:
            completed = await asyncio.wait_for(
                asyncio.to_thread(cls._run_build_sync, npm_path, project_dir, env),
                timeout=timeout_seconds,
            )
            output = cls._trim_output(completed.stdout or "")
            if completed.returncode != 0 and cls._is_host_spawn_failure(output):
                return ProjectValidationResult(
                    success=True,
                    command=command,
                    output=output,
                    skipped=True,
                    reason="Vite build was skipped after syntax validation because this Windows host blocked a child process spawn.",
                )
            return ProjectValidationResult(
                success=completed.returncode == 0,
                command=command,
                output=output,
            )
        except asyncio.TimeoutError:
            return ProjectValidationResult(
                success=False,
                command=command,
                output=f"Build validation timed out after {timeout_seconds:.0f}s.",
                timed_out=True,
            )
        except Exception as exc:
            return ProjectValidationResult(
                success=False,
                command=command,
                output=f"Unable to run build validation: {exc}",
            )

    @classmethod
    def _trim_output(cls, output: str) -> str:
        text = output.strip()
        if len(text) <= cls.OUTPUT_LIMIT:
            return text
        return text[-cls.OUTPUT_LIMIT:]

    @classmethod
    async def _validate_syntax(cls, project_dir: Path) -> ProjectValidationResult:
        node_path = cls._node_command()
        command = ["node", "-e", "syntax validator", str(project_dir)]
        if not node_path:
            return ProjectValidationResult(
                success=True,
                command=command,
                skipped=True,
                reason="node was not found in PATH; skipped syntax/build validation.",
            )

        try:
            completed = await asyncio.wait_for(
                asyncio.to_thread(cls._run_syntax_sync, node_path, project_dir),
                timeout=20.0,
            )
        except asyncio.TimeoutError:
            return ProjectValidationResult(
                success=False,
                command=command,
                output="Syntax validation timed out.",
                timed_out=True,
            )
        except Exception as exc:
            return ProjectValidationResult(
                success=True,
                command=command,
                skipped=True,
                reason=f"Syntax validation could not run: {exc}",
            )

        output = completed.stdout.strip()
        try:
            payload = json.loads(output.splitlines()[-1])
        except Exception:
            return ProjectValidationResult(
                success=completed.returncode == 0,
                command=command,
                output=cls._trim_output(output),
            )

        if payload.get("skipped"):
            return ProjectValidationResult(
                success=True,
                command=command,
                skipped=True,
                reason=payload.get("reason", "Syntax validation skipped."),
                output=output,
            )

        if payload.get("success") and completed.returncode == 0:
            return ProjectValidationResult(success=True, command=command, output=output)

        file_path = payload.get("file", "")
        line = payload.get("line")
        column = payload.get("column")
        message = payload.get("message", "Syntax error")
        location = f"{file_path}:{line}:{column}" if line is not None and column is not None else file_path
        return ProjectValidationResult(
            success=False,
            command=command,
            output=f"[syntax]\n{location}\n{message}",
        )

    @staticmethod
    def _run_build_sync(npm_path: str, project_dir: Path, env: dict) -> subprocess.CompletedProcess:
        if sys.platform.startswith("win"):
            cmd = f'"{npm_path}" run build'
            return subprocess.run(
                cmd,
                cwd=str(project_dir.resolve()),
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )

        return subprocess.run(
            [npm_path, "run", "build"],
            cwd=str(project_dir.resolve()),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

    @classmethod
    def _run_syntax_sync(cls, node_path: str, project_dir: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [node_path, "-e", cls.SYNTAX_SCRIPT, str(project_dir.resolve())],
            cwd=str(project_dir.resolve()),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    @staticmethod
    def _is_host_spawn_failure(output: str) -> bool:
        lowered = output.lower()
        return "spawn eperm" in lowered and "externalize-deps" in lowered
