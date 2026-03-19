import os
import json
import logging
from typing import Dict, Any, List
import google.generativeai as genai
from groq import Groq

from app.config import settings
from app.agents.base_agent import BaseAgent

genai.configure(api_key=settings.GEMINI_API_KEY)

class EditorAgent(BaseAgent):
    """Agent responsible for editing project files based on chat instructions."""
    
    def __init__(self):
        # We use a model that handles JSON reliably.
        self.gemini_model = genai.GenerativeModel("gemini-1.5-flash")
        
        # Groq Fallback Client
        self.groq_client = None
        if settings.GROQ_API_KEY:
            self.groq_client = Groq(api_key=settings.GROQ_API_KEY)
            self.groq_model = settings.GROQ_LLM_MODEL
            
    def _get_project_context(self, target_dir: str, prompt: str) -> str:
        """Read relevant files to provide context to the LLM, filtered by prompt."""
        context = ""
        directories_to_scan = [
            os.path.join(target_dir, "src", "pages"),
            os.path.join(target_dir, "src", "components"),
            os.path.join(target_dir, "src", "utils")
        ]
        
        prompt_lower = prompt.lower()
        files_collected = []
        
        for directory in directories_to_scan:
            if not os.path.exists(directory):
                continue
            for root, _, files in os.walk(directory):
                for file in files:
                    if file.endswith((".jsx", ".js", ".css")):
                        file_path = os.path.join(root, file)
                        files_collected.append(file_path)

        # Basic filtering to prevent hitting rate limits
        scored_files = []
        for fp in files_collected:
            score = 0
            name_lower = os.path.basename(fp).lower()
            name_no_ext = name_lower.replace('.jsx', '').replace('.js', '')
            
            if name_no_ext in prompt_lower:
                score += 10 # Explicit mention
            elif 'home' in name_lower or 'header' in name_lower or 'app' in name_lower:
                score += 1 # High-priority fallback pages
                
            scored_files.append((score, fp))
            
        # Sort by score descending
        scored_files.sort(key=lambda x: x[0], reverse=True)
        
        # Take top 3 files to strictly limit token size under free tier limits
        top_files = [fp for score, fp in scored_files[:3]]
        
        for file_path in top_files:
            rel_path = os.path.relpath(file_path, target_dir)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                context += f"\n--- {rel_path} ---\n{content}\n"
            except Exception as e:
                self.log(f"Failed to read {file_path}: {e}")
                
        return context

    async def execute_edit(self, project_id: str, user_message: str) -> Dict[str, Any]:
        self.log(f"Executing edit for project {project_id} with msg: {user_message}")
        
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        root_dir = os.path.dirname(backend_dir)
        target_dir = os.path.join(root_dir, 'user_projects', project_id)
        
        if not os.path.exists(target_dir):
            return {"error": "Project directory not found. Please wait for generation."}
            
        context = self._get_project_context(target_dir, user_message)
        
        prompt = f"""
        You are an expert AI software engineer for an e-commerce platform called ASEA.
        The user wants to make a change to their generated React frontend code.
        
        USER REQUEST: {user_message}
        
        CURRENT PROJECT CONTEXT:
        {context}
        
        Based on the user's request, figure out which file(s) need to be modified.
        Return the exact FULL CODE of the updated file(s) so we can overwrite them.
        Do not explain. Return ONLY valid JSON in this format:
        {{
            "agent_reply": "A friendly message to the user summarizing what you did.",
            "changes": [
                {{
                    "file_path": "src/pages/Home.jsx", 
                    "content": "..." 
                }}
            ]
        }}
        """
        
        try:
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
            
            # Apply changes
            await self._apply_changes(target_dir, parsed_response.get("changes", []))
            
            return {"reply": parsed_response.get("agent_reply", "I've applied the changes.")}
            
        except Exception as e:
            self.log(f"Gemini editing failed: {str(e)}")
            if self.groq_client:
                self.log(f"Falling back to Groq model {self.groq_model}")
                try:
                    chat_completion = self.groq_client.chat.completions.create(
                        messages=[
                            {"role": "user", "content": prompt}
                        ],
                        model=self.groq_model,
                        response_format={"type": "json_object"}
                    )
                    raw_json = chat_completion.choices[0].message.content
                    self.log("Received response from Groq EditorAgent")
                    parsed_response = json.loads(raw_json)
                    
                    # Apply changes
                    await self._apply_changes(target_dir, parsed_response.get("changes", []))
                    
                    return {"reply": parsed_response.get("agent_reply", "I've applied the changes using Groq fallback.")}
                except Exception as groq_e:
                    self.log(f"Groq fallback failed: {str(groq_e)}")
                    return {"error": f"Editing failed on both Gemini and Groq. groq error: {str(groq_e)}"}
            else:
                return {"error": f"Editing failed: {str(e)}"}
            
    async def _apply_changes(self, target_dir: str, changes: List[Dict[str, Any]]):
        for change in changes:
            rel_path = change.get("file_path")
            content = change.get("content")
            if not isinstance(rel_path, str) or not isinstance(content, str):
                continue
                
            file_path = os.path.join(target_dir, str(rel_path))
            # Ensure it is securely within target_dir
            if not os.path.abspath(file_path).startswith(os.path.abspath(target_dir)):
                self.log(f"Warning: path traversal attempt prevented: {rel_path}")
                continue
                
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(str(content))
            self.log(f"Rewrote file: {rel_path}")
