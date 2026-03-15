import google.generativeai as genai
import json
import logging
from typing import Dict, Any
from groq import Groq

from app.config import settings
from app.models.project import Specification, Requirement
from app.agents.base_agent import BaseAgent

genai.configure(api_key=settings.GEMINI_API_KEY)

class SpecificationAgent(BaseAgent):
    """Agent responsible for converting raw requirements into structured JSON specifications."""
    
    def __init__(self):
        # We use a model that handles JSON reliably.
        self.gemini_model = genai.GenerativeModel("gemini-1.5-flash")
        
        # Groq Fallback Client
        self.groq_client = None
        if settings.GROQ_API_KEY:
            self.groq_client = Groq(api_key=settings.GROQ_API_KEY)
            self.groq_model = settings.GROQ_LLM_MODEL
    
    async def generate_specification(self, requirement: Requirement) -> Dict[str, Any]:
        self.log(f"Generating specification for requirement {requirement.id}")
        
        prompt = f"""
        You are an expert software architect and product manager for an e-commerce platform.
        Given the following requirements, generate a complete JSON specification for the store.
        
        Category: {requirement.category}
        Preferences: {json.dumps(requirement.preferences) if requirement.preferences else "{}"}
        Raw Text: {requirement.raw_text}
        
        Provide the response as raw JSON ONLY conforming to this structure with no markdown or other formatting outside the JSON:
        {{
            "store_name": "...",
            "tagline": "...",
            "modules": ["auth", "products", "cart", "checkout"],
            "data_models": {{"tables": [...]}},
            "pages": ["Home", "Products", "Checkout"],
            "features": {{"reviews_enabled": true}},
            "api_structure": {{"policies": [...]}}
        }}
        """
        
        try:
            self.log("Attempting Gemini model")
            response = self.gemini_model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                )
            )
            raw_json = response.text
            self.log("Received response from Gemini")
            return json.loads(raw_json)
        except Exception as e:
            self.log(f"Gemini generation failed: {str(e)}")
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
                    self.log("Received response from Groq")
                    return json.loads(raw_json)
                except Exception as groq_e:
                    self.log(f"Groq fallback failed: {str(groq_e)}")
                    raise Exception(f"Both Gemini and Groq generation failed. Gemini: {e}, Groq: {groq_e}")
            else:
                raise e
