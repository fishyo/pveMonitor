import argparse
import logging
import os
import sys
import time
import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from collectors.pve_api import PVECollector
from collectors.hardware import HardwareCollector
from collectors.system_health import SystemHealthCollector
from engine.briefing import BriefingGenerator
from engine.alerter import AlertEngine
from engine.telegram_listener import TelegramBotListener
from notifiers.manager import NotificationManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("pveMonitor")

CONFIG_FILE = "config.yaml"
EXAMPLE_CONFIG_FILE = "config.example.yaml"

def load_config() -> dict:
    """加载 YAML 配置文件，自动支持环境变量覆盖 (Environment Variables Overlay)"""
    if not os.path.exists(CONFIG_FILE):
        if os.path.exists(EXAMPLE_CONFIG_FILE):
            logger.info(f"未找到 {CONFIG_FILE}，自动从模板创建配置文件...")
            with open(EXAMPLE_CONFIG_FILE, "r", encoding="utf-8") as f_src:
                content = f_src.read()
            with open(CONFIG_FILE, "w", encoding="utf-8") as f_dst:
                f_dst.write(content)
        else:
            logger.error("配置文件不存在且未找到模板 config.example.yaml！")
            sys.exit(1)
            
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # 支持环境变量动态覆盖敏感凭据
    if os.getenv("PVE_HOST"):
        cfg.setdefault("pve", {})["host"] = os.getenv("PVE_HOST")
    if os.getenv("PVE_PASSWORD"):
        cfg.setdefault("pve", {})["password"] = os.getenv("PVE_PASSWORD")
    if os.getenv("TG_BOT_TOKEN"):
        cfg.setdefault("notifiers", {}).setdefault("telegram", {})["bot_token"] = os.getenv("TG_BOT_TOKEN")
    if os.getenv("TG_CHAT_ID"):
        cfg.setdefault("notifiers", {}).setdefault("telegram", {})["chat_id"] = os.getenv("TG_CHAT_ID")
    if os.getenv("SMTP_PASSWORD") or os.getenv("GMAIL_PASSWORD"):
        cfg.setdefault("notifiers", {}).setdefault("email", {})["password"] = os.getenv("SMTP_PASSWORD") or os.getenv("GMAIL_PASSWORD")

    return cfg

class PVEMonitorApp:
    """PVE 监控服务主应用程序"""

    def __init__(self, config: dict):
        self.config = config
        self.pve_collector = PVECollector(config)
        self.hw_collector = HardwareCollector(config)
        self.health_collector = SystemHealthCollector(config)
        
        node_name = config.get("pve", {}).get("node_name", "pve")
        self.briefing_gen = BriefingGenerator(node_name=node_name)
        self.alert_engine = AlertEngine(config)
        self.notifier_mgr = NotificationManager(config)
        self.scheduler = None
        
        # 启动 Telegram Bot 交互指令监听器
        self.tg_listener = TelegramBotListener(config, self)
        self.tg_listener.start()

    def update_alert_job_interval(self, seconds: int):
        """动态更新或暂停/恢复 APScheduler 告警轮询任务 (安全防止 0 秒过度轮询)"""
        if not self.scheduler:
            return
        job = self.scheduler.get_job("alert_check")
        if seconds > 0:
            if job:
                try:
                    self.scheduler.reschedule_job("alert_check", trigger="interval", seconds=seconds)
                    self.scheduler.resume_job("alert_check")
                except Exception as e:
                    logger.warning(f"重新调度 alert_check 失败: {e}")
            else:
                self.scheduler.add_job(
                    self.run_alert_check_job,
                    trigger="interval",
                    seconds=seconds,
                    id="alert_check"
                )
            logger.info(f"告警轮询任务已成功生效: 每 {seconds} 秒检测一次")
        else:
            if job:
                try:
                    self.scheduler.remove_job("alert_check")
                except Exception as e:
                    logger.warning(f"移除 alert_check 任务失败: {e}")
            logger.info("告警轮询任务已成功暂停并移除调度队列")

    def run_briefing_job(self):
        """执行状态简报采集与发送任务"""
        logger.info("正在采集 PVE 数据并生成状态简报...")
        try:
            api_data = self.pve_collector.collect_all()
            hw_data = self.hw_collector.collect_all(pve_collector=self.pve_collector)
            health_data = self.health_collector.collect_all()

            brief_dict = self.briefing_gen.build_briefing_data(api_data, hw_data, health_data, self.config)
            markdown_content = self.briefing_gen.generate_markdown(brief_dict)
            html_content = self.briefing_gen.generate_html(brief_dict)
            tg_html_content = self.briefing_gen.generate_telegram_html(brief_dict)

            title = f"Proxmox VE 状态每日简报 ({brief_dict['node_name']})"
            self.notifier_mgr.broadcast_briefing(title, markdown_content, html_content, tg_html=tg_html_content)
        except Exception as e:
            logger.error(f"生成状态简报过程出错: {e}", exc_info=True)

    def run_alert_check_job(self):
        """执行即时异常预警检测任务"""
        try:
            api_data = self.pve_collector.collect_all()
            hw_data = self.hw_collector.collect_all()
            health_data = self.health_collector.collect_all()

            alerts = self.alert_engine.check_alerts(api_data, hw_data, health_data)
            for alert in alerts:
                logger.warning(f"触发警报通知: {alert['title']}")
                self.notifier_mgr.broadcast_alert(
                    title=alert["title"],
                    markdown_content=alert["content"]
                )
        except Exception as e:
            logger.error(f"预警检测过程出错: {e}")

def main():
    parser = argparse.ArgumentParser(description="Proxmox VE 状态简报与告警服务")
    parser.add_argument("--test-briefing", action="store_true", help="立即运行一次简报发送测试")
    parser.add_argument("--test-alert", action="store_true", help="发送一次测试异常告警")
    args = parser.parse_args()

    config = load_config()
    app = PVEMonitorApp(config)

    if args.test_briefing:
        logger.info("=== 触发一次测试简报 ===")
        app.run_briefing_job()
        return

    if args.test_alert:
        logger.info("=== 触发一次测试告警 ===")
        app.notifier_mgr.broadcast_alert(
            title="PVE 监控服务测试告警",
            markdown_content="这是一个测试告警消息，证明您的通知渠道配置正确且能够正常接收预警！"
        )
        return

    # 启动定时调度器
    scheduler = BackgroundScheduler()
    app.scheduler = scheduler

    # 1. 注册每日简报 Cron 任务
    briefing_cron = config.get("schedule", {}).get("briefing_cron", "0 8 * * *")
    try:
        scheduler.add_job(
            app.run_briefing_job,
            trigger=CronTrigger.from_crontab(briefing_cron),
            id="daily_briefing"
        )
        logger.info(f"已注册每日简报 Cron 任务: {briefing_cron}")
    except Exception as e:
        logger.error(f"解析 briefing_cron [{briefing_cron}] 失败: {e}")

    # 2. 注册预警检测 Interval 任务 (安全的 > 0 判定，防止重启后每 1 秒高频刷屏)
    alert_interval = config.get("schedule", {}).get("alert_interval_seconds", 120)
    if alert_interval > 0:
        scheduler.add_job(
            app.run_alert_check_job,
            trigger="interval",
            seconds=alert_interval,
            id="alert_check"
        )
        logger.info(f"已注册异常预警检测任务，间隔: {alert_interval} 秒")
    else:
        logger.info("异常预警轮询处于暂停状态 (alert_interval_seconds <= 0)")

    # 启动时是否先跑一次简报
    if config.get("schedule", {}).get("briefing_on_start", True):
        logger.info("服务启动，立即发送首条测试简报...")
        app.run_briefing_job()

    scheduler.start()
    logger.info("pveMonitor 监控服务已启动并进入后台轮询...")
    
    # 确保 logs 目录存在
    os.makedirs("logs", exist_ok=True)
    
    try:
        while True:
            # 刷新探针心跳文件
            with open("logs/heartbeat", "w", encoding="utf-8") as f:
                f.write(str(time.time()))
            time.sleep(5)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("pveMonitor 服务已停止")

if __name__ == "__main__":
    main()
