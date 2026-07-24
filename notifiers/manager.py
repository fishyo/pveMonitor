import logging
from typing import List
from .base import BaseNotifier
from .email_notifier import EmailNotifier
from .telegram_notifier import TelegramNotifier
from .webhook_notifier import WebhookNotifier

logger = logging.getLogger("pveMonitor.notifiers.manager")

class NotificationManager:
    """通知管理分发器"""

    def __init__(self, config: dict):
        self.config = config
        self.notifiers: List[BaseNotifier] = []
        self._init_notifiers()

    def _init_notifiers(self):
        self.notifiers.clear()
        # 1. Email 邮件
        email_n = EmailNotifier(self.config)
        if email_n.enabled:
            self.notifiers.append(email_n)
            logger.info("初始化 Notification: Email 已激活")

        # 2. Telegram
        tg_n = TelegramNotifier(self.config)
        if tg_n.enabled:
            self.notifiers.append(tg_n)
            logger.info("初始化 Notification: Telegram 已激活")

        # 3. Webhook
        wh_n = WebhookNotifier(self.config)
        if wh_n.enabled:
            self.notifiers.append(wh_n)
            logger.info(f"初始化 Notification: Webhook [{wh_n.webhook_type}] 已激活")

        if not self.notifiers:
            logger.warning("未开启任何通知渠道，所有简报和告警将仅输出到控制台日志！")

    def broadcast_briefing(self, title: str, markdown_content: str, html_content: str = None, tg_html: str = None):
        """向所有已启用的渠道发送简报"""
        logger.info(f"广播发送简报: {title}")
        for n in self.notifiers:
            if isinstance(n, TelegramNotifier):
                n.send_briefing(title, markdown_content, html_content, tg_html=tg_html)
            else:
                n.send_briefing(title, markdown_content, html_content)

    def broadcast_alert(self, title: str, markdown_content: str, html_content: str = None, tg_html: str = None):
        """向所有已启用的渠道发送告警"""
        logger.info(f"广播发送告警: {title}")
        for n in self.notifiers:
            if isinstance(n, TelegramNotifier):
                n.send_alert(title, markdown_content, html_content, tg_html=tg_html)
            else:
                n.send_alert(title, markdown_content, html_content)
