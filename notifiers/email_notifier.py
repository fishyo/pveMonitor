import logging
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .base import BaseNotifier

logger = logging.getLogger("pveMonitor.notifiers.email")

class EmailNotifier(BaseNotifier):
    """SMTP email notification dispatcher supporting responsive HTML briefings."""

    def __init__(self, config: dict):
        self.config = config.get("notifiers", {}).get("email", {})
        self.enabled = self.config.get("enabled", False)
        self.briefing_enabled = self.config.get("briefing_enabled", True)
        self.alert_enabled = self.config.get("alert_enabled", True)
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

        # Plaintext fallback payload
        part_text = MIMEText(markdown_content, "plain", "utf-8")
        msg.attach(part_text)

        # Responsive HTML payload
        if html_content:
            part_html = MIMEText(html_content, "html", "utf-8")
            msg.attach(part_html)

        server = None
        try:
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15)
                try:
                    server.starttls()
                except smtplib.SMTPNotSupportedError:
                    pass

            if self.username and self.password:
                server.login(self.username, self.password)

            server.sendmail(self.sender, self.receivers, msg.as_string())
            logger.info(f"邮件已成功发送至 {self.receivers}")
            return True
        except Exception as e:
            logger.error(f"发送邮件失败: {e}")
            return False
        finally:
            if server:
                try:
                    server.quit()
                except Exception:
                    try:
                        server.close()
                    except Exception:
                        pass

    def send_briefing(self, title: str, markdown_content: str, html_content: str = None) -> bool:
        if not self.briefing_enabled:
            logger.info("邮件简报推送已被设置禁用，跳过发送")
            return False
        subject = f"📊 【PVE 状态简报】{title}"
        return self._send_email(subject, markdown_content, html_content)

    def send_alert(self, title: str, markdown_content: str, html_content: str = None) -> bool:
        if not self.alert_enabled:
            logger.info("邮件告警推送已被设置禁用，跳过发送")
            return False
        subject = f"⚠️ 【PVE 紧急预警】{title}"
        return self._send_email(subject, markdown_content, html_content)
