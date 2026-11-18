from abc import ABC, abstractmethod

class BaseNotifier(ABC):
    """Abstract base class for notification dispatchers."""
    
    @abstractmethod
    def send_briefing(self, title: str, markdown_content: str, html_content: str = None) -> bool:
        """Send daily or scheduled status briefing."""
        pass

    @abstractmethod
    def send_alert(self, title: str, markdown_content: str, html_content: str = None) -> bool:
        """Send urgent threshold alert notification."""
        pass
