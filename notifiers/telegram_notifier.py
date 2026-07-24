import logging
import requests
from .base import BaseNotifier

logger = logging.getLogger("pveMonitor.notifiers.telegram")

class TelegramNotifier(BaseNotifier):
    """Telegram Bot 通知发送器"""

    def __init__(self, config: dict):
        self.config = config.get("notifiers", {}).get("telegram", {})
        self.enabled = self.config.get("enabled", False)
        self.bot_token = self.config.get("bot_token", "")
        self.chat_id = self.config.get("chat_id", "")

    def _send_msg(self, title: str, content: str) -> bool:
        if not self.enabled or not self.bot_token or not self.chat_id:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        text = f"<b>{title}</b>\n\n{content}"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("Telegram 消息已成功发送")
            return True
        except Exception as e:
            logger.error(f"Telegram 发送失败: {e}")
            return False

    def send_briefing(self, title: str, markdown_content: str, html_content: str = None, tg_html: str = None) -> bool:
        content = tg_html if tg_html else markdown_content
        return self._send_msg(f"📊 {title}", content)

    def send_alert(self, title: str, markdown_content: str, html_content: str = None, tg_html: str = None) -> bool:
        content = tg_html if tg_html else markdown_content
        return self._send_msg(f"⚠️ {title}", content)
