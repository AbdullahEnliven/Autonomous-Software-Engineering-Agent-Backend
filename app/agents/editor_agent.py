import os
import json
import logging
import re
import difflib
from typing import Dict, Any, List, Optional
import google.generativeai as genai
from groq import Groq

from app.config import settings
from app.agents.base_agent import BaseAgent
from app.utils.paths import get_project_dir

genai.configure(api_key=settings.GEMINI_API_KEY)


class EditorAgent(BaseAgent):
    """Powerful AI code editor agent using multi-step decomposition for small-context models.

    Strategy: Instead of stuffing everything into one prompt (which exceeds free-tier
    context limits), we decompose into focused steps:
      1. PLAN  – "which files need changing?" (small prompt with file tree only)
      2. EDIT  – one call per file with only that file's content (fits in context)
      3. APPLY – write to disk, auto-repair if patches fail
    """

    SCAN_EXTENSIONS = ('.jsx', '.js', '.tsx', '.ts', '.css', '.json', '.html', '.mjs', '.cjs')
    SKIP_DIRS = {'node_modules', '.git', 'dist', 'build', '.next', '__pycache__'}

    # Per-file caps (kept small for free-tier models)
    MAX_FILE_CHARS = 8000
    MAX_PLAN_TREE_LINES = 120

    def __init__(self):
        # --- Groq (primary) ---
        self.groq_client = None
        if settings.GROQ_API_KEY:
            self.groq_client = Groq(api_key=settings.GROQ_API_KEY)
            self.groq_model = settings.GROQ_LLM_MODEL



        # --- Gemini (fallback) ---
        self.gemini_model = None
        if settings.GEMINI_API_KEY:
            self.gemini_model = genai.GenerativeModel("gemini-1.5-flash")

        # Socket.IO references for real-time status
        self.sio = None
        self.sid = None

    # ------------------------------------------------------------------ utils
    async def _emit_status(self, status_type: str, message: str, details: Optional[Dict] = None):
        """Emit real-time status update to the connected client via Socket.IO."""
        if self.sio and self.sid:
            await self.sio.emit("agent_status", {
                "type": status_type,
                "message": message,
                "details": details or {}
            }, to=self.sid)
        self.log(f"[{status_type.upper()}] {message}")

    def _scan_project_files(self, target_dir: str) -> List[str]:
        """Scan the entire src/ directory tree for editable files."""
        files_collected = []
        src_dir = os.path.join(target_dir, "src")
        if not os.path.exists(src_dir):
            src_dir = target_dir
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if d not in self.SKIP_DIRS]
            for file in files:
                if file.endswith(self.SCAN_EXTENSIONS):
                    files_collected.append(os.path.join(root, file))
        return files_collected

    def _build_file_tree(self, target_dir: str, max_lines: int = 120) -> str:
        """Build a compact file tree string for the LLM."""
        tree_lines = []
        src_dir = os.path.join(target_dir, "src")
        if not os.path.exists(src_dir):
            src_dir = target_dir
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if d not in self.SKIP_DIRS]
            dirs.sort()
            level = os.path.relpath(root, target_dir).count(os.sep)
            indent = "  " * level
            dir_name = os.path.basename(root)
            tree_lines.append(f"{indent}{dir_name}/")
            sub_indent = "  " * (level + 1)
            for file in sorted(files):
                if file.endswith(self.SCAN_EXTENSIONS):
                    tree_lines.append(f"{sub_indent}{file}")
        return "\n".join(tree_lines[:max_lines])

    def _read_single_file(self, file_path: str, max_chars: int = 0) -> str:
        """Read a single file, truncating if needed."""
        cap = max_chars or self.MAX_FILE_CHARS
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            if len(content) > cap:
                head = int(cap * 0.7)
                tail = cap - head
                content = content[:head] + "\n/* ...truncated... */\n" + content[-tail:]
            return content
        except Exception as e:
            self.log(f"Failed to read {file_path}: {e}")
            return ""

    def _format_chat_history(self, chat_history: List[Dict]) -> str:
        """Format recent chat messages as context for the LLM."""
        if not chat_history:
            return ""
        lines = []
        for msg in chat_history[-4:]:  # Last 4 messages max
            role = msg.get("role", "user").upper()
            content = (msg.get("content") or msg.get("message") or "")[:300]
            lines.append(f"[{role}]: {content}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ LLM calls
    def _call_llm(self, prompt: str, expect_json: bool = True) -> str:
        """Call the best available LLM. Returns raw text."""
        errors = []

        # Try Groq (primary)
        if self.groq_client:
            try:
                self.log(f"Calling Groq ({self.groq_model})")
                kwargs = {
                    "messages": [{"role": "user", "content": prompt}],
                    "model": self.groq_model,
                    "temperature": 0.15,
                }
                if expect_json:
                    kwargs["response_format"] = {"type": "json_object"}
                resp = self.groq_client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content or ""
            except Exception as e:
                errors.append(f"Groq: {e}")
                self.log(f"Groq failed: {e}")

        # Try Gemini
        if self.gemini_model:
            try:
                self.log("Calling Gemini")
                config = {"temperature": 0.15}
                if expect_json:
                    config["response_mime_type"] = "application/json"
                resp = self.gemini_model.generate_content(
                    prompt,
                    generation_config=genai.GenerationConfig(**config),
                )
                return resp.text or ""
            except Exception as e:
                errors.append(f"Gemini: {e}")
                self.log(f"Gemini failed: {e}")

        raise RuntimeError("; ".join(errors) or "No LLM clients available")

    def _parse_json(self, raw: str) -> Dict[str, Any]:
        """Robustly parse JSON from LLM output."""
        if not raw or not raw.strip():
            raise ValueError("Empty LLM response")
        text = raw.strip()
        # Strip markdown fences
        fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if fence:
            text = fence.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                return json.loads(text[start:end + 1])
            # Try finding array
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end > start:
                return {"items": json.loads(text[start:end + 1])}
            raise

    # ------------------------------------------------------------------ STEP 1: PLAN
    def _build_plan_prompt(self, user_message: str, file_tree: str, chat_context: str) -> str:
        history_block = ""
        if chat_context:
            history_block = f"\nRECENT CHAT HISTORY:\n{chat_context}\n"

        return f"""You are an expert React/Vite code planner.
The user wants to change their e-commerce store.{history_block}
USER REQUEST: {user_message}

PROJECT FILE TREE:
{file_tree}

Respond with JSON only. List which files need to be modified, created, or deleted.
For each file, write a short task description of what to change.

{{
  "plan": "brief overall plan",
  "file_tasks": [
    {{"file_path": "src/components/Header.jsx", "action": "modify", "task": "Add a search bar to the header"}},
    {{"file_path": "src/pages/SearchPage.jsx", "action": "create", "task": "Create a new search results page"}}
  ]
}}

Rules:
- action must be one of: modify, create, delete
- file_path is relative to the project root (e.g. src/pages/Home.jsx)
- Keep the list focused. Only include files that actually need changes.
- For routing changes, include the router/App file too.
- Maximum 6 files per plan."""

    # ------------------------------------------------------------------ STEP 2: EDIT (per file)
    def _build_edit_prompt(self, user_message: str, task: str, file_path: str,
                           current_content: str, action: str) -> str:
        if action == "create":
            return f"""You are an expert React/Vite developer.
Create a new file: {file_path}

TASK: {task}
USER REQUEST: {user_message}

Return JSON only:
{{
  "file_path": "{file_path}",
  "content": "...complete file content..."
}}

Rules:
- Write complete, production-ready React/JSX code.
- Include all imports.
- Use Tailwind CSS for styling.
- Export the component as default."""

        # For modify action: send the file content and ask for the new version
        return f"""You are an expert React/Vite developer editing an existing file.

FILE: {file_path}
TASK: {task}
USER REQUEST: {user_message}

CURRENT FILE CONTENT:
{current_content}

Return JSON only with the complete new file content:
{{
  "file_path": "{file_path}",
  "content": "...complete updated file content..."
}}

Rules:
- Return the COMPLETE file content, not just the changed parts.
- Preserve all unrelated code, imports, and exports.
- Maintain valid JSX/JS syntax.
- Keep the same coding style as the original."""

    # ------------------------------------------------------------------ path safety
    def _normalize_file_path(self, rel_path: str) -> str:
        return str(rel_path or "").replace("\\", "/").lstrip("/")

    def _safe_file_path(self, target_dir: str, rel_path: str) -> Optional[str]:
        clean_rel = self._normalize_file_path(rel_path)
        if not clean_rel:
            return None
        base = os.path.abspath(target_dir)
        candidate = os.path.abspath(os.path.join(base, clean_rel))
        try:
            if os.path.commonpath([base, candidate]) != base:
                return None
        except ValueError:
            return None
        return candidate

    # ------------------------------------------------------------------ fuzzy patch (kept for repair)
    def _find_fuzzy_span(self, existing: str, old_text: str) -> Optional[tuple]:
        old_lines = old_text.splitlines()
        existing_lines = existing.splitlines(keepends=True)
        if not old_lines or not existing_lines:
            return None
        normalized_old = [line.strip() for line in old_lines if line.strip()]
        if not normalized_old:
            return None
        window = len(normalized_old)
        stripped_existing = [line.strip() for line in existing_lines]
        for start_line in range(0, len(stripped_existing) - window + 1):
            if stripped_existing[start_line:start_line + window] == normalized_old:
                start = sum(len(line) for line in existing_lines[:start_line])
                end = sum(len(line) for line in existing_lines[:start_line + window])
                return start, end
        best = difflib.SequenceMatcher(None, old_text, existing).find_longest_match(
            0, len(old_text), 0, len(existing)
        )
        if best.size >= max(40, int(len(old_text) * 0.82)):
            return best.b, best.b + best.size
        return None

    def _apply_patch_edits(self, existing: str, edits: List[Dict]) -> tuple:
        updated = existing
        applied = 0
        skipped = []
        for edit in edits:
            old_text = edit.get("old_text")
            new_text = edit.get("new_text", "")
            if not isinstance(old_text, str) or not old_text:
                skipped.append("Patch edit skipped: missing old_text")
                continue
            if old_text in updated:
                updated = updated.replace(old_text, new_text, 1)
                applied += 1
                continue
            crlf_old = old_text.replace("\n", "\r\n")
            if crlf_old in updated:
                updated = updated.replace(crlf_old, new_text.replace("\n", "\r\n"), 1)
                applied += 1
                continue
            span = self._find_fuzzy_span(updated, old_text)
            if span:
                start, end = span
                updated = updated[:start] + new_text + updated[end:]
                applied += 1
                continue
            skipped.append(f"Patch not found: {old_text[:60]!r}")
        return updated, applied, skipped

    def _is_full_rewrite_requested(self, user_message: str) -> bool:
        msg = (user_message or "").lower()
        return any(k in msg for k in [
            "rewrite", "rebuild", "replace entire", "from scratch", "overhaul", "redo whole"
        ])

    # ------------------------------------------------------------------ MAIN EXECUTE
    async def execute_edit(self, project_id: str, user_message: str,
                           chat_history: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Execute a multi-step edit with decomposition for small-context models."""
        self.log(f"Executing edit for project {project_id} with msg: {user_message}")

        target_dir = str(get_project_dir(project_id))
        if not os.path.exists(target_dir):
            return {"error": "Project directory not found. Please wait for generation."}

        # ---- Step 1: Scan ----
        await self._emit_status("scanning", "Scanning project files...", {"step": 1, "total_steps": 4})
        all_files = self._scan_project_files(target_dir)
        file_tree = self._build_file_tree(target_dir)
        await self._emit_status("scanning", f"Found {len(all_files)} editable files", {
            "step": 1, "total_steps": 4, "file_count": len(all_files)
        })

        # ---- Step 2: Plan (small LLM call — file tree only, no file contents) ----
        await self._emit_status("planning", "Planning changes with AI...", {"step": 2, "total_steps": 4})
        chat_context = self._format_chat_history(chat_history or [])

        try:
            plan_prompt = self._build_plan_prompt(user_message, file_tree, chat_context)
            plan_raw = self._call_llm(plan_prompt, expect_json=True)
            plan_data = self._parse_json(plan_raw)
        except Exception as e:
            self.log(f"Planning failed: {e}")
            await self._emit_status("error", "Failed to plan changes", {"step": 2, "total_steps": 4})
            return {"error": f"Planning failed: {e}"}

        file_tasks = plan_data.get("file_tasks") or plan_data.get("items") or []
        plan_summary = plan_data.get("plan", "")

        if not file_tasks:
            return {
                "error": "The agent couldn't determine which files to change. Try a more specific instruction.",
                "files_modified": [],
            }

        await self._emit_status("planning", f"Plan: {len(file_tasks)} file(s) to change", {
            "step": 2, "total_steps": 4,
            "files": [t.get("file_path", "") for t in file_tasks],
        })

        # ---- Step 3: Edit each file individually (one LLM call per file) ----
        await self._emit_status("writing", "Generating code changes...", {"step": 3, "total_steps": 4})
        modified_files = []
        skipped_all = []
        rewrite_allowed = self._is_full_rewrite_requested(user_message)

        for i, task_item in enumerate(file_tasks[:6]):  # Cap at 6 files
            rel_path = self._normalize_file_path(task_item.get("file_path", ""))
            action = (task_item.get("action") or "modify").lower()
            task_desc = task_item.get("task", user_message)

            if not rel_path:
                skipped_all.append("Skipped: empty file_path in plan")
                continue

            file_path = self._safe_file_path(target_dir, rel_path)
            if not file_path:
                skipped_all.append(f"Skipped: unsafe path {rel_path}")
                continue

            await self._emit_status("writing",
                f"Editing {rel_path} ({i+1}/{len(file_tasks)})...",
                {"step": 3, "total_steps": 4, "current_file": rel_path})

            if action == "delete":
                if os.path.exists(file_path):
                    os.remove(file_path)
                    modified_files.append(rel_path)
                    self.log(f"Deleted: {rel_path}")
                continue

            # Read current content (empty for create)
            current_content = ""
            if action != "create" and os.path.exists(file_path):
                current_content = self._read_single_file(file_path)

            if action == "modify" and not os.path.exists(file_path):
                action = "create"

            try:
                edit_prompt = self._build_edit_prompt(
                    user_message, task_desc, rel_path, current_content, action
                )
                edit_raw = self._call_llm(edit_prompt, expect_json=True)
                edit_data = self._parse_json(edit_raw)
            except Exception as e:
                skipped_all.append(f"LLM failed for {rel_path}: {e}")
                self.log(f"Edit call failed for {rel_path}: {e}")
                continue

            new_content = edit_data.get("content")
            edits = edit_data.get("edits")

            # If the LLM returned patch-style edits instead of full content
            if edits and isinstance(edits, list) and current_content:
                updated, applied, patch_skipped = self._apply_patch_edits(current_content, edits)
                skipped_all.extend([f"{rel_path}: {s}" for s in patch_skipped])
                if applied > 0 and updated != current_content:
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(updated)
                    modified_files.append(rel_path)
                    self.log(f"Patched: {rel_path} ({applied} edits)")
                elif not new_content:
                    skipped_all.append(f"No effective patches for {rel_path}")
                continue

            if not isinstance(new_content, str) or not new_content.strip():
                skipped_all.append(f"Empty content returned for {rel_path}")
                continue

            # Safety: avoid destructive rewrites unless explicitly asked
            if (action == "modify" and current_content and not rewrite_allowed
                    and len(new_content) < len(current_content) * 0.3):
                looks_valid = any(kw in new_content for kw in [
                    "export default", "export {", "function ", "const ", "import "
                ])
                if not looks_valid:
                    skipped_all.append(f"Blocked tiny rewrite for {rel_path}")
                    continue

            if current_content and new_content.strip() == current_content.strip():
                skipped_all.append(f"No changes detected for {rel_path}")
                continue

            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            modified_files.append(rel_path)
            self.log(f"{'Created' if action == 'create' else 'Modified'}: {rel_path}")

        # ---- Step 4: Report ----
        if not modified_files:
            await self._emit_status("error", "No files were changed.", {
                "step": 4, "total_steps": 4, "skipped": skipped_all[:5]
            })
            return {
                "error": "I planned the change but couldn't apply edits to the files. Try a more specific instruction or ask me to rebuild the target page.",
                "files_modified": [],
            }

        await self._emit_status("complete", f"Applied changes to {len(modified_files)} file(s)!", {
            "step": 4, "total_steps": 4, "files_modified": modified_files,
        })

        # Build a friendly reply
        agent_reply = plan_data.get("agent_reply") or f"Done! I updated {len(modified_files)} file(s): {', '.join(modified_files)}."

        return {
            "reply": agent_reply,
            "plan": plan_summary,
            "files_modified": sorted(set(modified_files)),
        }
