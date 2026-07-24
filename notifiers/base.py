from abc import ABC, abstractmethod

class BaseNotifier(ABC):
    """通知发送基类"""
    
    @abstractmethod
    def send_briefing(self, title: str, markdown_content: str, html_content: str = None) -> bool:
        """发送状态简报"""
        pass

    @abstractmethod
    def send_alert(self, title: str, markdown_content: str, html_content: str = None) -> bool:
        """发送异常警告"""
        pass
