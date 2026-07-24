import logging
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .base import BaseNotifier

logger = logging.getLogger("pveMonitor.notifiers.email")

class EmailNotifier(BaseNotifier):
    """邮件 SMTP 通知发送器 (包含响应式 HTML 简报)"""

    def __init__(self, config: dict):
        self.config = config.get("notifiers", {}).get("email", {})
        self.enabled = self.config.get("enabled", False)
        self.smtp_host = self.config.get("smtp_host", "")
        self.smtp_port = self.config.get("smtp_port", 465)
        self.use_ssl = self.config.get("use_ssl", True)
        self.username = self.config.get("username", "")
        self.password = self.config.get("password", "")
        self.sender = self.config.get("sender", self.username)
        self.receivers = self.config.get("receivers", [])

    def _send_email(self, subject: str, markdown_content: str, html_content: str = None) -> bool:
        if not self.enabled:
            return False

        if not self.smtp_host or not self.receivers:
            logger.error("邮件配置不完整 (缺少 smtp_host 或 receivers)")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.receivers)

        # 纯文本备用部分
        part_text = MIMEText(markdown_content, "plain", "utf-8")
        msg.attach(part_text)

        # HTML 内容部分
        if html_content:
            part_html = MIMEText(html_content, "html", "utf-8")
            msg.attach(part_html)

        try:
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15)
                server.starttls()

            if self.username and self.password:
                server.login(self.username, self.password)

            server.sendmail(self.sender, self.receivers, msg.as_string())
            server.quit()
            logger.info(f"邮件已成功发送至 {self.receivers}")
            return True
        except Exception as e:
            logger.error(f"发送邮件失败: {e}")
            return False

    def send_briefing(self, title: str, markdown_content: str, html_content: str = None) -> bool:
        subject = f"📊 【PVE 状态简报】{title}"
        return self._send_email(subject, markdown_content, html_content)

    def send_alert(self, title: str, markdown_content: str, html_content: str = None) -> bool:
        subject = f"⚠️ 【PVE 紧急预警】{title}"
        return self._send_email(subject, markdown_content, html_content)
