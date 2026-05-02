import json
import re

from app.utils.groq_client import get_groq_client

from app.config import settings


class NameSelectorService:
    @staticmethod
    def _sanitize_name(value: str) -> str:
        if not value:
            return "Untitled Store"

        cleaned = re.sub(r"[^a-zA-Z0-9\s&'\-]", "", value).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not cleaned:
            return "Untitled Store"

        # Keep names readable and short for UI and slug generation.
        words = cleaned.split(" ")
        clipped = " ".join(words[:5])
        return clipped[:48].strip() or "Untitled Store"

    @staticmethod
    def _fallback_name(requirements: str, category: str | None = None) -> str:
        base = (category or "Store").strip() or "Store"
        text = (requirements or "").lower()

        hints = [
            ("Fashion", ["fashion", "apparel", "clothing", "streetwear", "boutique"]),
            ("Tech", ["electronics", "gadgets", "smart", "laptop", "phone"]),
            ("Beauty", ["beauty", "skincare", "cosmetics", "makeup"]),
            ("Home", ["furniture", "decor", "home", "interior"]),
            ("Sport", ["sport", "fitness", "gym", "running"]),
            ("Food", ["food", "snack", "coffee", "kitchen"]),
        ]

        for label, tokens in hints:
            if any(token in text for token in tokens):
                return f"{label} Hub"

        return f"{base} Hub"

    @classmethod
    def select_name_with_groq(
        cls,
        requirements: str,
        category: str | None = None,
        target_market: str | None = None,
    ) -> str:
        client = get_groq_client()
        if not client:
            return cls._fallback_name(requirements, category)

        prompt = f"""
You are a world-class ecommerce brand namer.
Generate ONE short, memorable, brand-safe store name.

Inputs:
- Category: {category or 'General'}
- Target market: {target_market or 'General audience'}
- Store description: {requirements or ''}

Rules:
- 2 to 4 words max
- No punctuation-heavy names
- No copyrighted brand names
- Make it premium and marketable
- Output JSON only: {{"store_name":"..."}}
""".strip()

        try:
            completion = client.chat.completions.create(
                model=settings.GROQ_LLM_MODEL,
                temperature=0.5,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
            )
            text = completion.choices[0].message.content if completion.choices else ""
            payload = json.loads(text or "{}")
            return cls._sanitize_name(payload.get("store_name", ""))
        except Exception:
            return cls._fallback_name(requirements, category)
