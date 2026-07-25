import logging
import threading
import time
import requests
import yaml

CONFIG_FILE = "config.yaml"
logger = logging.getLogger("pveMonitor.telegram_bot")

class TelegramBotListener:
    """Telegram Bot 交互式指令与参数修改监听器 (后台线程)"""

    def __init__(self, config: dict, app_instance):
        self.config = config
        self.app = app_instance
        self.tg_cfg = config.get("notifiers", {}).get("telegram", {})
        self.enabled = self.tg_cfg.get("enabled", False)
        self.bot_token = self.tg_cfg.get("bot_token", "")
        self.chat_id = str(self.tg_cfg.get("chat_id", ""))
        
        self.offset = 0
        self.running = False
        self.thread = None
        self.start_time = 0
        self.last_status_time = 0

    def start(self):
        if not self.enabled or not self.bot_token:
            logger.info("Telegram Bot 未启用或未配置 token，跳过交互监听。")
            return
        self.running = True
        self.start_time = time.time()
        self._flush_old_updates()
        self.thread = threading.Thread(target=self._poll_updates, daemon=True)
        self.thread.start()
        logger.info("Telegram Bot 交互指令监听已启动...")

    def _flush_old_updates(self):
        """清空启动前离线期间积累的 Telegram 历史待处理消息 (防止重启后批量重复触发指令)"""
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        try:
            resp = requests.get(url, params={"offset": -1, "timeout": 5}, timeout=10)
            if resp.status_code == 200:
                updates = resp.json().get("result", [])
                if updates:
                    latest_id = updates[-1]["update_id"]
                    self.offset = latest_id + 1
                    logger.info(f"Telegram Bot 已清理历史待处理消息队列，最新 offset: {self.offset}")
        except Exception as e:
            logger.warning(f"Telegram Bot 清理历史消息队列失败: {e}")

    def stop(self):
        self.running = False

    def _save_config_and_reload(self, new_config: dict):
        """写入并重新加载 config.yaml"""
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.safe_dump(new_config, f, allow_unicode=True, sort_keys=False)
        logger.info("已通过 Telegram 指令更新 config.yaml")

    def _send_reply(self, chat_id: str, text: str, parse_mode: str = "Markdown"):
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode}, timeout=10)
        except Exception as e:
            logger.error(f"Telegram 回复消息失败: {e}")

    def _handle_command(self, chat_id: str, text: str):
        # 安全验证: 仅响应配置中的白名单 chat_id
        if self.chat_id and str(chat_id) != self.chat_id:
            logger.warning(f"拒绝未经授权的 Telegram 交互请求, Chat ID: {chat_id}")
            self._send_reply(chat_id, "⛔ 未授权的 Chat ID，拒绝操作。")
            return

        cmd_parts = text.strip().split()
        cmd = cmd_parts[0].lower()

        if cmd in ["/start", "/help"]:
            help_msg = """🤖 **PVE 监控服务 Telegram Bot 指令列表**:

📊 **查询与控制类指令**:
• `/status` - 立即触发一次实时 PVE 状态简报 (仅 Telegram 框架内回复)
• `/temp` - 单独查询当前硬件温度
• `/cancel` - 强行清空所有积压的历史指令并重置排队状态
• `/help` - 显示帮助列表

⚙️ **参数修改指令**:
• `/set_cpu <温度>` - 动态修改 CPU 告警温度 (如 `/set_cpu 80`)
• `/set_mem <百分比>` - 动态修改内存告警比例 (如 `/set_mem 85`)
• `/set_nvme <温度>` - 动态修改 NVMe 固态告警温度 (如 `/set_nvme 65`)

🌐 **流量维度开关指令**:
• `/toggle_daily` - 开启 / 关闭 24h 日流量统计
• `/toggle_weekly` - 开启 / 关闭 7d 周流量统计
• `/toggle_monthly` - 开启 / 关闭 30d 月流量统计
• `/toggle_total` - 开启 / 关闭 开机至今总流量统计

🔘 **通知开关指令**:
• `/toggle_email` - 一键开启 / 关闭邮件通知
• `/toggle_alert` - 一键暂停 / 恢复异常告警
"""
            self._send_reply(chat_id, help_msg)

        elif cmd in ["/cancel", "/clear", "/stop_queue"]:
            self.last_status_time = 0
            self._flush_old_updates()
            self._send_reply(
                chat_id,
                "🧹 **已成功清空 Telegram 待处理消息队列！**\n"
                "所有积压的历史指令已丢弃，频控限制已解开，Bot 已恢复全新就绪状态。"
            )

        elif cmd in ["/status", "/pve"]:
            now = time.time()
            if now - self.last_status_time < 15:
                self._send_reply(chat_id, "⚠️ 简报生成请求过于频繁，请稍后再试。")
                return
            self.last_status_time = now
            self._send_reply(chat_id, "🔄 正在为您实时采集 PVE 节点数据，请稍候...")
            try:
                brief_data = self.app.generate_briefing()
                self._send_reply(chat_id, brief_data["tg_html"], parse_mode="HTML")
            except Exception as e:
                self._send_reply(chat_id, f"❌ 采集过程出错: {e}")

        elif cmd in ["/temp", "/temperature"]:
            try:
                temps = self.app.hw_collector.get_temperatures()
                lines = ["🌡️ **实时硬件温度**"]

                cpu_temp = temps.get("cpu_temp")
                lines.append(
                    f"• CPU Package: `{cpu_temp:.1f}°C`"
                    if isinstance(cpu_temp, (int, float))
                    else "• CPU Package: `未检测到`"
                )

                cpu_cores = temps.get("cpu_cores", [])
                if cpu_cores:
                    core_values = " / ".join(f"{value:.1f}°C" for value in cpu_cores)
                    lines.append(f"• CPU 核心: `{core_values}`")

                for label, key in [("NVMe", "nvme_temps"), ("硬盘", "hdd_temps")]:
                    devices = temps.get(key, {})
                    if devices:
                        values = "；".join(
                            f"{name}: {value:.1f}°C"
                            for name, value in devices.items()
                            if isinstance(value, (int, float))
                        )
                        if values:
                            lines.append(f"• {label}: `{values}`")

                lines.append("\n_温度为当前快照，PVE RRD 不提供 24h 温度历史。_")
                self._send_reply(chat_id, "\n".join(lines))
            except Exception as e:
                logger.error(f"实时温度采集失败: {e}")
                self._send_reply(chat_id, "❌ 温度采集失败，请检查容器的传感器访问权限。")

        elif cmd == "/toggle_daily":
            tr_cfg = self.config.setdefault("traffic", {})
            curr = tr_cfg.get("show_daily", True)
            tr_cfg["show_daily"] = not curr
            self._save_config_and_reload(self.config)
            status_str = "🟢 已开启" if not curr else "🔴 已关闭"
            self._send_reply(chat_id, f"🌐 **流量维度变更**: 24h 日流量统计已切换为 **{status_str}**！")

        elif cmd == "/toggle_weekly":
            tr_cfg = self.config.setdefault("traffic", {})
            curr = tr_cfg.get("show_weekly", True)
            tr_cfg["show_weekly"] = not curr
            self._save_config_and_reload(self.config)
            status_str = "🟢 已开启" if not curr else "🔴 已关闭"
            self._send_reply(chat_id, f"🌐 **流量维度变更**: 7d 周流量统计已切换为 **{status_str}**！")

        elif cmd == "/toggle_monthly":
            tr_cfg = self.config.setdefault("traffic", {})
            curr = tr_cfg.get("show_monthly", True)
            tr_cfg["show_monthly"] = not curr
            self._save_config_and_reload(self.config)
            status_str = "🟢 已开启" if not curr else "🔴 已关闭"
            self._send_reply(chat_id, f"🌐 **流量维度变更**: 30d 月流量统计已切换为 **{status_str}**！")

        elif cmd == "/toggle_total":
            tr_cfg = self.config.setdefault("traffic", {})
            curr = tr_cfg.get("show_total", True)
            tr_cfg["show_total"] = not curr
            self._save_config_and_reload(self.config)
            status_str = "🟢 已开启" if not curr else "🔴 已关闭"
            self._send_reply(chat_id, f"🌐 **流量维度变更**: 开机累计总流量统计已切换为 **{status_str}**！")

        elif cmd == "/toggle_email":
            email_cfg = self.config.setdefault("notifiers", {}).setdefault("email", {})
            curr = email_cfg.get("enabled", False)
            email_cfg["enabled"] = not curr
            self._save_config_and_reload(self.config)
            self.app.notifier_mgr._init_notifiers()
            status_str = "🟢 已开启" if not curr else "🔴 已关闭"
            self._send_reply(chat_id, f"🔔 **通知开关变更**: 邮件通知已切换为 **{status_str}**！")

        elif cmd == "/toggle_alert":
            alert_interval = self.config.setdefault("schedule", {}).get("alert_interval_seconds", 120)
            if alert_interval > 0:
                self.config.setdefault("schedule", {})["alert_interval_seconds"] = 0
                new_sec = 0
                status_str = "🔴 已暂停 (后台已停止轮询)"
            else:
                self.config.setdefault("schedule", {})["alert_interval_seconds"] = 120
                new_sec = 120
                status_str = "🟢 已恢复 (每 2 分钟轮询一次)"
            self._save_config_and_reload(self.config)
            self.app.update_alert_job_interval(new_sec)
            self._send_reply(chat_id, f"⚠️ <b>告警引擎状态</b>: 异常告警已切换为 <b>{status_str}</b>！")

        elif cmd == "/set_cpu":
            if len(cmd_parts) > 1 and cmd_parts[1].isdigit():
                val = int(cmd_parts[1])
                self.config.setdefault("thresholds", {}).setdefault("temperature", {})["cpu_warning"] = val
                self._save_config_and_reload(self.config)
                self._send_reply(chat_id, f"✅ **成功调整参数**: CPU 告警阈值已修改为 **{val}°C**！")
            else:
                self._send_reply(chat_id, "⚠️ 格式错误，用法示例: `/set_cpu 80`")

        elif cmd == "/set_mem":
            if len(cmd_parts) > 1 and cmd_parts[1].isdigit():
                val = int(cmd_parts[1])
                self.config.setdefault("thresholds", {}).setdefault("memory", {})["usage_percent_warning"] = val
                self._save_config_and_reload(self.config)
                self._send_reply(chat_id, f"✅ **成功调整参数**: 物理内存告警阈值已修改为 **{val}%**！")
            else:
                self._send_reply(chat_id, "⚠️ 格式错误，用法示例: `/set_mem 85`")

        elif cmd == "/set_nvme":
            if len(cmd_parts) > 1 and cmd_parts[1].isdigit():
                val = int(cmd_parts[1])
                self.config.setdefault("thresholds", {}).setdefault("temperature", {})["nvme_warning"] = val
                self._save_config_and_reload(self.config)
                self._send_reply(chat_id, f"✅ **成功调整参数**: NVMe 告警阈值已修改为 **{val}°C**！")
            else:
                self._send_reply(chat_id, "⚠️ 格式错误，用法示例: `/set_nvme 65`")

    def _poll_updates(self):
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        while self.running:
            try:
                resp = requests.get(url, params={"offset": self.offset, "timeout": 10}, timeout=15)
                if resp.status_code == 200:
                    updates = resp.json().get("result", [])
                    for update in updates:
                        self.offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        msg_date = msg.get("date", 0)
                        # 过滤掉启动前收到的离线旧消息 (允许 10 秒时钟偏差)
                        if self.start_time and msg_date and msg_date < (self.start_time - 10):
                            logger.info(f"跳过 Telegram 历史待处理消息 (date: {msg_date})")
                            continue
                        chat_id = msg.get("chat", {}).get("id")
                        text = msg.get("text", "")
                        if text and chat_id:
                            threading.Thread(target=self._handle_command, args=(chat_id, text), daemon=True).start()
            except Exception as e:
                time.sleep(5)
            time.sleep(1)
