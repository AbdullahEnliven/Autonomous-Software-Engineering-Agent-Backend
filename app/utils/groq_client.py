import logging
from groq import Groq
from app.config import settings

logger = logging.getLogger(__name__)

class GroqChatCompletionsWrapper:
    def __init__(self, fallback_client):
        self.fallback_client = fallback_client

    def create(self, **kwargs):
        return self.fallback_client.get_completion(**kwargs)

class GroqChatWrapper:
    def __init__(self, fallback_client):
        self.completions = GroqChatCompletionsWrapper(fallback_client)

class GroqFallbackClient:
    def __init__(self):
        # Parse comma separated keys
        raw_keys = getattr(settings, "GROQ_API_KEYS", "") 
        if not raw_keys and hasattr(settings, "GROQ_API_KEY"):
            # Fallback for old `.env` config if present
            raw_keys = getattr(settings, "GROQ_API_KEY", "")
        self.api_keys = [k.strip() for k in raw_keys.split(',') if k.strip()]
        self.current_index = 0
        self.clients = [Groq(api_key=key) for key in self.api_keys]
        self.chat = GroqChatWrapper(self)

    @property
    def has_keys(self) -> bool:
        return len(self.api_keys) > 0

    def get_completion(self, **kwargs):
        if not self.has_keys:
            raise Exception("No Groq API keys configured")
            
        attempts = 0
        last_error = None
        
        while attempts < len(self.api_keys):
            client = self.clients[self.current_index]
            try:
                response = client.chat.completions.create(**kwargs)
                return response
            except Exception as e:
                error_str = str(e).lower()
                if "429" in error_str or "rate limit" in error_str or "too many requests" in error_str:
                    logger.warning(f"Groq API key at index {self.current_index} hit rate limit. Switching to next key.")
                    self.current_index = (self.current_index + 1) % len(self.api_keys)
                    attempts += 1
                    last_error = e
                else:
                    # Non-rate-limit error (e.g. invalid request, authentication fail)
                    raise e
                    
        raise Exception(f"All Groq API keys failed or hit limits. Last error: {last_error}")

def get_groq_client():
    client = GroqFallbackClient()
    return client if client.has_keys else None
