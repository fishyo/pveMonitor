import logging
import requests
from .base import BaseNotifier

logger = logging.getLogger("pveMonitor.notifiers.webhook")

class WebhookNotifier(BaseNotifier):
    """Webhook 多渠道通知发送器 (支持 飞书 / 钉钉 / 企业微信 / Server酱 / Bark / PushDeer)"""

    def __init__(self, config: dict):
        self.config = config.get("notifiers", {}).get("webhook", {})
        self.enabled = self.config.get("enabled", False)
        self.webhook_type = self.config.get("type", "generic").lower()
        self.url = self.config.get("url", "")

    def _send(self, title: str, markdown_content: str) -> bool:
        if not self.enabled or not self.url:
            return False

        headers = {"Content-Type": "application/json"}
        payload = {}

        if self.webhook_type == "feishu":
            payload = {
                "msg_type": "interactive",
                "card": {
                    "header": {"title": {"tag": "plain_text", "content": title}},
                    "elements": [{"tag": "markdown", "content": markdown_content}]
                }
            }
        elif self.webhook_type == "dingtalk":
            payload = {
                "msgtype": "markdown",
                "markdown": {"title": title, "text": f"### {title}\n{markdown_content}"}
            }
        elif self.webhook_type == "wechat_work":
            payload = {
                "msgtype": "markdown",
                "markdown": {"content": f"### {title}\n{markdown_content}"}
            }
        elif self.webhook_type == "serverchan":
            payload = {"title": title, "desp": markdown_content}
        elif self.webhook_type == "bark":
            payload = {"title": title, "body": markdown_content}
        elif self.webhook_type == "pushdeer":
            payload = {"text": title, "desp": markdown_content}
        else: # Generic Webhook
            payload = {"title": title, "content": markdown_content}

        try:
            resp = requests.post(self.url, json=payload, headers=headers, timeout=10)
            resp.raise_for_status()
            logger.info(f"Webhook [{self.webhook_type}] 发送成功")
            return True
        except Exception as e:
            logger.error(f"Webhook [{self.webhook_type}] 发送失败: {e}")
            return False

    def send_briefing(self, title: str, markdown_content: str, html_content: str = None) -> bool:
        return self._send(f"📊 {title}", markdown_content)

    def send_alert(self, title: str, markdown_content: str, html_content: str = None) -> bool:
        return self._send(f"⚠️ {title}", markdown_content)
