import os
import json
import logging
import re
from typing import Dict, Any, List, Optional
import google.generativeai as genai
from groq import Groq

from app.config import settings
from app.agents.base_agent import BaseAgent
from app.utils.paths import get_project_dir

genai.configure(api_key=settings.GEMINI_API_KEY)

class EditorAgent(BaseAgent):
    """Powerful AI code editor agent with multi-step reasoning and real-time status updates."""
    
    # File extensions to include when scanning
    SCAN_EXTENSIONS = ('.jsx', '.js', '.tsx', '.ts', '.css', '.json')
    # Directories to skip
    SKIP_DIRS = {'node_modules', '.git', 'dist', 'build', '.next', '__pycache__'}
    # Maximum files to include in context (ranked by relevance)
    MAX_CONTEXT_FILES = 8
    # Hard caps to keep prompts within model limits
    MAX_FILE_CHARS = 3000
    MAX_TOTAL_CONTEXT_CHARS = 15000
    FALLBACK_MAX_CONTEXT_FILES = 4
    FALLBACK_MAX_FILE_CHARS = 1800
    FALLBACK_MAX_TOTAL_CONTEXT_CHARS = 7000
    FALLBACK_FILE_TREE_LINES = 28
    
    def __init__(self):
        # Always use Groq client first, fallback currently acts as the primary
        self.groq_client = None
        if settings.GROQ_API_KEY:
            self.groq_client = Groq(api_key=settings.GROQ_API_KEY)
            self.groq_model = settings.GROQ_LLM_MODEL
            
        self.gemini_model = None
        if settings.GEMINI_API_KEY:
            self.gemini_model = genai.GenerativeModel("gemini-1.5-flash")
        
        # Socket.IO references for real-time status
        self.sio = None
        self.sid = None

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
            # Fallback: scan target_dir itself
            src_dir = target_dir
        
        for root, dirs, files in os.walk(src_dir):
            # Skip ignored directories
            dirs[:] = [d for d in dirs if d not in self.SKIP_DIRS]
            for file in files:
                if file.endswith(self.SCAN_EXTENSIONS):
                    files_collected.append(os.path.join(root, file))
        
        return files_collected

    def _rank_files(self, files: List[str], prompt: str, target_dir: str) -> List[str]:
        """Rank files by relevance to the user's prompt."""
        prompt_lower = prompt.lower()
        prompt_words = set(prompt_lower.split())
        
        scored_files = []
        for fp in files:
            score = 0
            rel_path = os.path.relpath(fp, target_dir).lower()
            name_lower = os.path.basename(fp).lower()
            name_no_ext = os.path.splitext(name_lower)[0]
            
            # Direct file name mention in prompt
            if name_no_ext in prompt_lower:
                score += 20
            
            # Partial word matches in the relative path
            for word in prompt_words:
                if len(word) > 2 and word in rel_path:
                    score += 5
            
            # High-priority files (layout, main, app, index, home, header)
            priority_names = {'app', 'main', 'index', 'home', 'header', 'footer', 'layout', 'navbar', 'sidebar'}
            if name_no_ext in priority_names:
                score += 3
            
            # Pages and components get a slight boost
            if 'pages' in rel_path or 'components' in rel_path:
                score += 2
            
            # Config files
            if name_no_ext in {'tailwind.config', 'vite.config', 'package'}:
                score += 1
            
            scored_files.append((score, fp))
        
        # Sort by score descending
        scored_files.sort(key=lambda x: x[0], reverse=True)
        return [fp for _, fp in scored_files[:self.MAX_CONTEXT_FILES]]

    def _read_files_context(
        self,
        file_paths: List[str],
        target_dir: str,
        max_file_chars: Optional[int] = None,
        max_total_chars: Optional[int] = None,
    ) -> str:
        """Read file contents and format as context string."""
        context = ""
        total_chars = 0
        per_file_cap = max_file_chars or self.MAX_FILE_CHARS
        total_cap = max_total_chars or self.MAX_TOTAL_CONTEXT_CHARS

        for file_path in file_paths:
            if total_chars >= total_cap:
                break

            rel_path = os.path.relpath(file_path, target_dir)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                if len(content) > per_file_cap:
                    content = content[:per_file_cap] + "\n/* ...truncated for token safety... */\n"

                block = f"\n--- {rel_path} ---\n{content}\n"
                remaining = total_cap - total_chars
                if len(block) > remaining:
                    block = block[:remaining]

                context += block
                total_chars += len(block)
            except Exception as e:
                self.log(f"Failed to read {file_path}: {e}")

        return context

    def _build_file_tree(self, target_dir: str, max_lines: int = 60) -> str:
        """Build a compact file tree string for the LLM to understand project structure."""
        tree_lines = []
        src_dir = os.path.join(target_dir, "src")
        if not os.path.exists(src_dir):
            src_dir = target_dir
        
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if d not in self.SKIP_DIRS]
            level = os.path.relpath(root, target_dir).count(os.sep)
            indent = "  " * level
            dir_name = os.path.basename(root)
            tree_lines.append(f"{indent}{dir_name}/")
            sub_indent = "  " * (level + 1)
            for file in sorted(files):
                if file.endswith(self.SCAN_EXTENSIONS):
                    tree_lines.append(f"{sub_indent}{file}")
        
        return "\n".join(tree_lines[:max_lines])  # Cap to prevent token overflow

    def _build_prompt(self, user_message: str, file_tree: str, context: str) -> str:
        return f"""
        You are an expert AI software engineer working on a React/Vite e-commerce project.
        The user wants to make a change to their generated frontend code.

        USER REQUEST: {user_message}

        PROJECT FILE TREE:
        {file_tree}

        RELEVANT FILE CONTENTS:
        {context}

        INSTRUCTIONS:
        1. Analyze the current codebase and understand the existing patterns and styles.
        2. Plan the minimal set of changes needed to fulfill the user's request.
        3. You can MODIFY existing files or CREATE new ones.
        4. Prefer PATCH-style edits for existing files using exact find/replace snippets.
        5. Do NOT rewrite whole files for small tasks (e.g., add social links in footer).
        6. Preserve all unrelated code, structure, imports, and existing behavior.
        7. Ensure all React components remain valid JSX.

        Return ONLY valid JSON in this exact format:
        {{
            "plan": "A brief description of what you decided to do and why.",
            "agent_reply": "A friendly, concise message to the user summarizing the changes made.",
            "changes": [
                {{
                    "file_path": "src/components/Footer.jsx",
                    "action": "patch",
                    "edits": [
                        {{
                            "old_text": "...exact old snippet...",
                            "new_text": "...replacement snippet..."
                        }}
                    ]
                }}
            ],
            "files_modified": ["src/components/Footer.jsx"]
        }}

        Notes:
        - Use action "create" with "content" only for brand new files.
        - Use action "modify" with full "content" ONLY if user explicitly asks to rewrite/rebuild entire file.
        """

    def _build_fallback_prompt(self, user_message: str, file_tree: str, context: str) -> str:
        return f"""
        You are a precise React/Vite code editor.
        User request: {user_message}

        File tree (truncated):
        {file_tree}

        Code context (truncated):
        {context}

        Respond with JSON only:
        {{
          "plan": "short plan",
          "agent_reply": "short summary",
          "changes": [{{"file_path":"src/file.jsx","action":"patch","edits":[{{"old_text":"...","new_text":"..."}}]}}],
          "files_modified": ["src/file.jsx"]
        }}

        Rules:
        - Keep edits minimal and targeted.
        - Modify only necessary files.
        - Preserve unrelated code; do not remove existing sections unless asked.
        - Ensure valid JSX/JS syntax.
        """

    def _is_full_rewrite_requested(self, user_message: str) -> bool:
        msg = (user_message or "").lower()
        rewrite_keywords = [
            "rewrite",
            "rebuild",
            "replace entire",
            "from scratch",
            "overhaul",
            "redo whole",
        ]
        return any(k in msg for k in rewrite_keywords)

    def _apply_patch_edits(self, existing: str, edits: List[Dict[str, Any]]) -> str:
        updated = existing
        for edit in edits:
            old_text = edit.get("old_text")
            new_text = edit.get("new_text", "")
            if not isinstance(old_text, str) or not isinstance(new_text, str) or not old_text:
                continue

            # Replace only the first exact match to avoid broad destructive edits.
            if old_text in updated:
                updated = updated.replace(old_text, new_text, 1)
            else:
                # If exact matching fails, keep file unchanged for this edit.
                self.log("Patch edit skipped: old_text not found exactly.")
        return updated

    async def execute_edit(self, project_id: str, user_message: str) -> Dict[str, Any]:
        """Execute a multi-step edit with real-time status updates."""
        self.log(f"Executing edit for project {project_id} with msg: {user_message}")
        
        target_dir = str(get_project_dir(project_id))
        
        if not os.path.exists(target_dir):
            return {"error": "Project directory not found. Please wait for generation."}
        
        # Step 1: Scan project files
        await self._emit_status("scanning", "Scanning project files...", {"step": 1, "total_steps": 4})
        all_files = self._scan_project_files(target_dir)
        file_tree = self._build_file_tree(target_dir)
        
        await self._emit_status("scanning", f"Found {len(all_files)} editable files", {
            "step": 1, "total_steps": 4, "file_count": len(all_files)
        })
        
        # Step 2: Rank and read relevant files
        await self._emit_status("analyzing", "Analyzing relevant files...", {"step": 2, "total_steps": 4})
        ranked_files = self._rank_files(all_files, user_message, target_dir)
        context = self._read_files_context(
            ranked_files,
            target_dir,
            max_file_chars=self.MAX_FILE_CHARS,
            max_total_chars=self.MAX_TOTAL_CONTEXT_CHARS,
        )
        
        files_read = [os.path.relpath(f, target_dir) for f in ranked_files]
        await self._emit_status("analyzing", f"Read {len(ranked_files)} relevant files", {
            "step": 2, "total_steps": 4, "files_read": files_read
        })
        
        # Step 3: Plan and generate changes via LLM
        await self._emit_status("planning", "Planning changes with AI...", {"step": 3, "total_steps": 4})

        prompt = self._build_prompt(user_message, file_tree, context)
        
        try:
            if self.groq_client:
                self.log(f"Attempting Groq model {self.groq_model}")
                await self._emit_status("planning", f"Planning changes with Groq {self.groq_model}...", {"step": 3, "total_steps": 4})
                
                try:
                    fallback_files = ranked_files[:self.FALLBACK_MAX_CONTEXT_FILES]
                    fallback_tree = self._build_file_tree(target_dir, max_lines=self.FALLBACK_FILE_TREE_LINES)
                    fallback_context = self._read_files_context(
                        fallback_files,
                        target_dir,
                        max_file_chars=self.FALLBACK_MAX_FILE_CHARS,
                        max_total_chars=self.FALLBACK_MAX_TOTAL_CONTEXT_CHARS,
                    )
                    fallback_prompt = self._build_fallback_prompt(user_message, fallback_tree, fallback_context)

                    chat_completion = self.groq_client.chat.completions.create(
                        messages=[
                            {"role": "user", "content": fallback_prompt}
                        ],
                        model=self.groq_model,
                        response_format={"type": "json_object"}
                    )
                    raw_json = chat_completion.choices[0].message.content
                    self.log("Received response from Groq EditorAgent")
                    parsed_response = json.loads(raw_json)
                except Exception as groq_e:
                    self.log(f"Groq failed: {str(groq_e)}")
                    if self.gemini_model:
                        self.log("Falling back to Gemini model")
                        await self._emit_status("planning", "Groq failed, switching to Gemini API...", {"step": 3, "total_steps": 4})
                        response = self.gemini_model.generate_content(
                            prompt,
                            generation_config=genai.GenerationConfig(
                                response_mime_type="application/json",
                            )
                        )
                        raw_json = response.text
                        self.log("Received response from Gemini EditorAgent via fallback")
                        parsed_response = json.loads(raw_json)
                    else:
                        await self._emit_status("error", "Failed to generate changes via Groq (No Gemini fallback)", {"step": 3, "total_steps": 4})
                        return {"error": f"Editing failed on Groq. Error: {str(groq_e)}"}
            elif self.gemini_model:
                self.log("Attempting Gemini model for EditorAgent")
                response = self.gemini_model.generate_content(
                    prompt,
                    generation_config=genai.GenerationConfig(
                        response_mime_type="application/json",
                    )
                )
                raw_json = response.text
                self.log("Received response from Gemini EditorAgent")
                parsed_response = json.loads(raw_json)
            else:
                 await self._emit_status("error", "Failed to generate changes, no LLM configured.", {"step": 3, "total_steps": 4})
                 return {"error": "No LLM clients available."}

        except Exception as e:
            self.log(f"Editing generation failed: {str(e)}")
            await self._emit_status("error", "Failed to generate changes", {"step": 3, "total_steps": 4})
            return {"error": f"Editing failed: {str(e)}"}
        
        # Step 4: Apply changes
        changes = parsed_response.get("changes", [])
        files_modified = parsed_response.get("files_modified", [])
        
        await self._emit_status("writing", f"Applying {len(changes)} file change(s)...", {
            "step": 4, "total_steps": 4, "files": files_modified
        })
        
        await self._apply_changes(target_dir, changes, user_message)
        
        # Done
        await self._emit_status("complete", "All changes applied successfully!", {
            "step": 4, "total_steps": 4, "files_modified": files_modified
        })
        
        return {
            "reply": parsed_response.get("agent_reply", "I've applied the changes."),
            "plan": parsed_response.get("plan", ""),
            "files_modified": files_modified
        }
            
    async def _apply_changes(self, target_dir: str, changes: List[Dict[str, Any]], user_message: str):
        """Write file changes to disk."""
        rewrite_allowed = self._is_full_rewrite_requested(user_message)

        for change in changes:
            rel_path = change.get("file_path")
            action = (change.get("action") or "patch").lower()
            if not isinstance(rel_path, str):
                continue

            file_path = os.path.join(target_dir, str(rel_path))
            # Security: ensure path stays within target_dir
            if not os.path.abspath(file_path).startswith(os.path.abspath(target_dir)):
                self.log(f"Warning: path traversal attempt prevented: {rel_path}")
                continue

            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Preferred path: patch existing files with targeted edits.
            edits = change.get("edits") if isinstance(change.get("edits"), list) else []
            if action == "patch" and edits:
                if not os.path.exists(file_path):
                    self.log(f"Patch skipped, file missing: {rel_path}")
                    continue
                with open(file_path, "r", encoding="utf-8") as f:
                    existing = f.read()
                updated = self._apply_patch_edits(existing, edits)
                if updated != existing:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(updated)
                    self.log(f"Patched file: {rel_path}")
                else:
                    self.log(f"No effective patch changes for: {rel_path}")
                continue

            content = change.get("content")
            if not isinstance(content, str):
                continue

            if action == "create":
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(str(content))
                self.log(f"Created file: {rel_path}")
                continue

            if action == "modify":
                # Guardrail: avoid destructive full rewrites unless explicitly asked.
                if os.path.exists(file_path) and not rewrite_allowed:
                    with open(file_path, "r", encoding="utf-8") as f:
                        existing = f.read()
                    if existing and len(content) < int(len(existing) * 0.6):
                        self.log(f"Blocked destructive rewrite for: {rel_path}")
                        continue

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(str(content))
                self.log(f"Modified file: {rel_path}")
