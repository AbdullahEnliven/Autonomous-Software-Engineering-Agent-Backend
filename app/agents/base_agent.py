from abc import ABC

class BaseAgent(ABC):
    """Base class for all generation agents in the pipeline."""
    
    def log(self, message: str):
        """Standardized logging function for the agent."""
        # For now, print. In a real system, use structlog and emit to Socket.IO.
        print(f"[{self.__class__.__name__}] {message}")
