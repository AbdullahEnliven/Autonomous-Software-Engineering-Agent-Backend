import json
import re
from typing import Dict, List, Optional

import httpx
import google.generativeai as genai
from groq import Groq

from app.config import settings


genai.configure(api_key=settings.GEMINI_API_KEY)


class StoreImageKeywordAgent:
    """Generates strong photo search queries using LLM, with deterministic fallback rules."""

    def __init__(self):
        self.gemini_model = genai.GenerativeModel("gemini-1.5-flash")
        self.groq_client = Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None

    def _fallback_queries(self, store_name: str, store_description: str) -> Dict[str, str]:
        text = f"{store_name} {store_description}".lower()

        rule_map = [
            ("fashion", ["fashion", "clothing", "apparel", "streetwear", "boutique"]),
            ("electronics", ["electronics", "gadgets", "smartphone", "laptop", "tech"]),
            ("furniture", ["furniture", "sofa", "chair", "interior", "decor"]),
            ("beauty", ["beauty", "skincare", "cosmetics", "makeup", "wellness"]),
            ("jewelry", ["jewelry", "watch", "ring", "necklace", "luxury"]),
            ("food", ["food", "snacks", "coffee", "restaurant", "kitchen"]),
            ("sports", ["sports", "fitness", "workout", "running", "training"]),
        ]

        detected = "retail"
        for label, tokens in rule_map:
            if any(token in text for token in tokens):
                detected = label
                break

        hero = f"{detected} product hero shot clean studio lighting ecommerce"
        essentials = f"{detected} premium products flat lay minimal background"
        arrivals = f"new {detected} collection product photography modern"
        sale = f"{detected} shopping sale concept lifestyle image"

        return {
            "hero": hero,
            "essentials": essentials,
            "arrivals": arrivals,
            "sale": sale,
        }

    def _parse_json_queries(self, text: str) -> Optional[Dict[str, str]]:
        if not text:
            return None

        json_match = re.search(r"\{[\s\S]*\}", text)
        if not json_match:
            return None

        try:
            data = json.loads(json_match.group(0))
        except Exception:
            return None

        required_keys = ["hero", "essentials", "arrivals", "sale"]
        if not all(isinstance(data.get(k), str) and data.get(k).strip() for k in required_keys):
            return None

        return {k: data[k].strip() for k in required_keys}

    def generate_queries(self, store_name: str, store_description: str) -> Dict[str, str]:
        fallback = self._fallback_queries(store_name, store_description)

        prompt = f"""
You are an ecommerce visual search strategist.
Generate high-quality, specific search queries for a stock photo API.
Store name: {store_name}
Store description: {store_description}

Return ONLY valid JSON in this exact shape:
{{
  "hero": "...",
  "essentials": "...",
  "arrivals": "...",
  "sale": "..."
}}

Rules:
- Queries should be 6-12 words.
- Must describe product photography scenes, not logos.
- No brand names.
- Focus on commercial ecommerce visuals.
""".strip()

        try:
            response = self.gemini_model.generate_content(prompt)
            parsed = self._parse_json_queries(getattr(response, "text", ""))
            if parsed:
                return parsed
        except Exception:
            pass

        if self.groq_client:
            try:
                completion = self.groq_client.chat.completions.create(
                    model=settings.GROQ_LLM_MODEL,
                    temperature=0.2,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = completion.choices[0].message.content if completion.choices else ""
                parsed = self._parse_json_queries(content)
                if parsed:
                    return parsed
            except Exception:
                pass

        return fallback


class StoreImagePersonalizationService:
    """
    Rule-based slot replacement + AI-assisted keyword generation + Pexels fetching.
    """

    @staticmethod
    def _search_pexels(query: str, orientation: str = "landscape", per_page: int = 10) -> List[str]:
        if not settings.PEXELS_API_KEY:
            return []

        url = "https://api.pexels.com/v1/search"
        headers = {"Authorization": settings.PEXELS_API_KEY}
        params = {
            "query": query,
            "per_page": per_page,
            "orientation": orientation,
            "size": "large",
        }

        try:
            with httpx.Client(timeout=12.0) as client:
                response = client.get(url, headers=headers, params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return []

        photos = payload.get("photos") or []
        urls: List[str] = []
        for photo in photos:
            src = photo.get("src") or {}
            candidate = src.get("large2x") or src.get("large") or src.get("original")
            if isinstance(candidate, str) and candidate.startswith("http"):
                urls.append(candidate)

        return urls

    @classmethod
    def get_store_images(cls, store_name: str, store_description: str) -> Optional[Dict[str, str]]:
        if not settings.PEXELS_API_KEY:
            return None

        agent = StoreImageKeywordAgent()
        queries = agent.generate_queries(store_name=store_name, store_description=store_description)

        hero_candidates = cls._search_pexels(queries["hero"], orientation="portrait", per_page=10)
        essentials_candidates = cls._search_pexels(queries["essentials"], orientation="landscape", per_page=10)
        arrivals_candidates = cls._search_pexels(queries["arrivals"], orientation="landscape", per_page=10)
        sale_candidates = cls._search_pexels(queries["sale"], orientation="landscape", per_page=10)

        used = set()

        def pick(candidates: List[str]) -> Optional[str]:
            for item in candidates:
                if item not in used:
                    used.add(item)
                    return item
            return None

        selected = {
            "hero": pick(hero_candidates),
            "essentials": pick(essentials_candidates),
            "arrivals": pick(arrivals_candidates),
            "sale": pick(sale_candidates),
        }

        if not all(selected.values()):
            return None

        return selected
