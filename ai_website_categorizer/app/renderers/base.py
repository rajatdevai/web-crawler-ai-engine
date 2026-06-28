from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
from app.models.page import RenderMethod

@dataclass
class RenderResult:
    raw_html: str = ""
    final_url: str = ""
    http_status: int = 0
    render_method: RenderMethod = RenderMethod.STATIC
    render_duration_ms: int = 0
    page_title: str = ""
    detected_technologies: List[str] = field(default_factory=list)
    error: Optional[str] = None

class BaseRenderer(ABC):
    @abstractmethod
    async def render(self, url: str) -> RenderResult:
        """
        Renders the URL and returns a RenderResult.
        Must NEVER raise an exception. Failures are captured in the 'error' field.
        """
        pass
