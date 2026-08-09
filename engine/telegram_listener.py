import logging
import threading
import time
import requests
import yaml

CONFIG_FILE = "config.yaml"
logger = logging.getLogger("pveMonitor.telegram_bot")

class TelegramBotListener:
    """Telegram Bot 交互式管理中心与指令监听器 (后台线程)"""

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
        logger.info("Telegram Bot 交互管理中心监听已启动...")

    def _flush_old_updates(self):
        """清空启动前离线期间积累的 Telegram 历史待处理消息"""
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

    def _send_reply(self, chat_id: str, text: str, parse_mode: str = "HTML", reply_markup: dict = None):
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Telegram 回复消息失败: {e}")

    def _edit_message(self, chat_id: str, message_id: int, text: str, parse_mode: str = "HTML", reply_markup: dict = None):
        url = f"https://api.telegram.org/bot{self.bot_token}/editMessageText"
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Telegram 修改消息失败: {e}")

    def _answer_callback(self, callback_query_id: str, text: str = ""):
        url = f"https://api.telegram.org/bot{self.bot_token}/answerCallbackQuery"
        payload = {"callback_query_id": callback_query_id, "text": text}
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Telegram 应答 callback query 失败: {e}")

    # ==================== 页面面板构建器 (Menu Builders) ====================

    def _build_manage_menu(self) -> tuple[str, dict]:
        """构建主管理中心面板 (Manage Control Center)"""
        node_name = self.config.get("pve", {}).get("node_name", "pve")
        alert_interval = self.config.get("schedule", {}).get("alert_interval_seconds", 120)
        alert_status = f"🟢 轮询中 ({alert_interval}s)" if alert_interval > 0 else "🔴 已暂停"
        key_vms = self.config.get("thresholds", {}).get("vms", {}).get("key_vm_ids", [])
        key_vms_count = f"{len(key_vms)} 个实例" if key_vms else "全部 (未指定)"

        text = (
            f"🎛️ <b>Proxmox VE 监控服务 · 管理中心 (/manage)</b>\n\n"
            f"📍 <b>节点名称</b>: <code>{node_name}</code>\n"
            f"⚠️ <b>告警引擎</b>: <code>{alert_status}</code>\n"
            f"🖥️ <b>重点监控</b>: <code>{key_vms_count}</code>\n\n"
            f"点击下方按钮进行模块化配置与诊断："
        )
        keyboard = [
            [
                {"text": "🖥️ 实例监控点选", "callback_data": "m_vms"},
                {"text": "⚙️ 告警阈值配置", "callback_data": "m_thresholds"}
            ],
            [
                {"text": "🔔 通知开关控制", "callback_data": "m_notifiers"},
                {"text": "🌐 流量维度设置", "callback_data": "m_traffic"}
            ],
            [
                {"text": "📊 实时简报快照", "callback_data": "cmd_status"},
                {"text": "🌡️ 硬件温度快照", "callback_data": "cmd_temp"}
            ],
            [
                {"text": "❓ 帮助指南", "callback_data": "m_help"},
                {"text": "❌ 关闭管理中心", "callback_data": "m_close"}
            ]
        ]
        return text, {"inline_keyboard": keyboard}

    def _build_vm_menu(self) -> tuple[str, dict]:
        """从 PVE 自动获取所有实例 ID 与名称，构建带开关与返回按钮的可视化面板"""
        vm_cfg = self.config.get("thresholds", {}).get("vms", {})
        alert_on = vm_cfg.get("alert_on_stopped", True)
        key_vms = list(vm_cfg.get("key_vm_ids", []))

        guests = []
        try:
            if hasattr(self.app, "pve_collector") and self.app.pve_collector:
                api_data = self.app.pve_collector.collect_all()
                all_guests = api_data.get("vms", []) + api_data.get("lxcs", [])
                for g in all_guests:
                    g_id = g.get("vmid") or g.get("id")
                    if g_id is not None:
                        g_name = g.get("name", "Unknown")
                        g_status = g.get("status", "unknown")
                        guests.append({"id": int(g_id), "name": g_name, "status": g_status})
        except Exception as e:
            logger.warning(f"从 PVE API 获取实例列表失败: {e}")

        if not guests and key_vms:
            for g_id in key_vms:
                guests.append({"id": g_id, "name": f"VM-{g_id}", "status": "unknown"})

        seen = set()
        unique_guests = []
        for g in guests:
            if g["id"] not in seen:
                seen.add(g["id"])
                unique_guests.append(g)
        unique_guests.sort(key=lambda x: x["id"])

        status_str = "🟢 已开启" if alert_on else "🔴 已关闭"
        key_vms_str = ", ".join(str(x) for x in key_vms) if key_vms else "全部实例 (默认监控所有)"

        text = (
            f"🖥️ <b>PVE 实例重点监控配置面板</b>\n\n"
            f"• 停机告警总开关: <b>{status_str}</b>\n"
            f"• 当前重点监控列表: <code>{key_vms_str}</code>\n\n"
            f"👇 <b>点击下方实例按钮可实时“点选/取消”重点监控</b>："
        )

        keyboard = []
        row = []
        for g in unique_guests:
            g_id = g["id"]
            g_name = g["name"]
            is_key = g_id in key_vms
            icon = "🟢" if is_key else "⚪"
            btn_text = f"{icon} [{g_id}] {g_name}"
            row.append({"text": btn_text, "callback_data": f"toggle_vm_{g_id}"})
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        toggle_alert_text = "🔴 关闭停机告警" if alert_on else "🟢 开启停机告警"
        keyboard.append([
            {"text": f"🔔 {toggle_alert_text}", "callback_data": "vm_action_toggle_alert"},
            {"text": "🧹 监控全部(清空)", "callback_data": "vm_action_clear"}
        ])

        keyboard.append([
            {"text": "🔙 返回管理中心", "callback_data": "m_manage"},
            {"text": "❌ 关闭菜单", "callback_data": "m_close"}
        ])

        return text, {"inline_keyboard": keyboard}

    def _build_thresholds_menu(self) -> tuple[str, dict]:
        """构建告警阈值调整面板 (Thresholds Panel)"""
        th = self.config.get("thresholds", {})
        temp_th = th.get("temperature", {})
        mem_th = th.get("memory", {})

        cpu_warning = temp_th.get("cpu_warning", 75)
        nvme_warning = temp_th.get("nvme_warning", 60)
        mem_warning = mem_th.get("usage_percent_warning", 90)

        text = (
            f"⚙️ <b>告警预警阈值设置面板</b>\n\n"
            f"🔥 <b>CPU 告警温度</b>: <code>{cpu_warning}°C</code>\n"
            f"🔥 <b>NVMe 告警温度</b>: <code>{nvme_warning}°C</code>\n"
            f"🧠 <b>物理内存预警比例</b>: <code>{mem_warning}%</code>\n\n"
            f"👇 <b>使用下方按钮快速调节参数</b>："
        )

        keyboard = [
            [
                {"text": f"🔥 CPU: {cpu_warning}°C ⬇️", "callback_data": "th_cpu_-5"},
                {"text": f"🔥 CPU: {cpu_warning}°C ⬆️", "callback_data": "th_cpu_+5"}
            ],
            [
                {"text": f"🔥 NVMe: {nvme_warning}°C ⬇️", "callback_data": "th_nvme_-5"},
                {"text": f"🔥 NVMe: {nvme_warning}°C ⬆️", "callback_data": "th_nvme_+5"}
            ],
            [
                {"text": f"🧠 内存: {mem_warning}% ⬇️", "callback_data": "th_mem_-5"},
                {"text": f"🧠 内存: {mem_warning}% ⬆️", "callback_data": "th_mem_+5"}
            ],
            [
                {"text": "🔙 返回管理中心", "callback_data": "m_manage"},
                {"text": "❌ 关闭菜单", "callback_data": "m_close"}
            ]
        ]
        return text, {"inline_keyboard": keyboard}

    def _build_notifiers_menu(self) -> tuple[str, dict]:
        """构建通知渠道控制面板 (Notifiers Panel)"""
        n_cfg = self.config.get("notifiers", {})
        tg_briefing = n_cfg.get("telegram", {}).get("briefing_enabled", True)
        email_enabled = n_cfg.get("email", {}).get("enabled", False)
        alert_interval = self.config.get("schedule", {}).get("alert_interval_seconds", 120)

        tg_str = "🟢 开启" if tg_briefing else "🔴 关闭"
        email_str = "🟢 开启" if email_enabled else "🔴 关闭"
        alert_str = f"🟢 运行中 ({alert_interval}s)" if alert_interval > 0 else "🔴 已暂停"

        text = (
            f"🔔 <b>通知渠道与轮询控制面板</b>\n\n"
            f"• Telegram 定时简报推送: <b>{tg_str}</b>\n"
            f"• 邮件 notification 状态: <b>{email_str}</b>\n"
            f"• 异常预警后台轮询: <b>{alert_str}</b>\n\n"
            f"点击下方按钮进行切换："
        )

        keyboard = [
            [
                {"text": f"🔔 TG简报: {tg_str}", "callback_data": "n_tg_briefing"},
                {"text": f"📧 邮件通知: {email_str}", "callback_data": "n_email"}
            ],
            [
                {"text": f"⚠️ 后台告警轮询: {alert_str}", "callback_data": "n_alert_engine"}
            ],
            [
                {"text": "🔙 返回管理中心", "callback_data": "m_manage"},
                {"text": "❌ 关闭菜单", "callback_data": "m_close"}
            ]
        ]
        return text, {"inline_keyboard": keyboard}

    def _build_traffic_menu(self) -> tuple[str, dict]:
        """构建流量统计维度开关面板 (Traffic Dimensions Panel)"""
        tr = self.config.get("traffic", {})
        d = "🟢 开" if tr.get("show_daily", True) else "🔴 关"
        w = "🟢 开" if tr.get("show_weekly", True) else "🔴 关"
        m = "🟢 开" if tr.get("show_monthly", True) else "🔴 关"
        t = "🟢 开" if tr.get("show_total", True) else "🔴 关"

        text = (
            f"🌐 <b>简报流量统计维度配置面板</b>\n\n"
            f"• 24h 日流量统计: <b>{d}</b>\n"
            f"• 7d 周流量统计: <b>{w}</b>\n"
            f"• 30d 月流量统计: <b>{m}</b>\n"
            f"• 开机至今累计总流量: <b>{t}</b>\n\n"
            f"点击下方按钮切换对应维度的显示与隐藏："
        )

        keyboard = [
            [
                {"text": f"24h 日流量: {d}", "callback_data": "tr_daily"},
                {"text": f"7d 周流量: {w}", "callback_data": "tr_weekly"}
            ],
            [
                {"text": f"30d 月流量: {m}", "callback_data": "tr_monthly"},
                {"text": f"累计总流量: {t}", "callback_data": "tr_total"}
            ],
            [
                {"text": "🔙 返回管理中心", "callback_data": "m_manage"},
                {"text": "❌ 关闭菜单", "callback_data": "m_close"}
            ]
        ]
        return text, {"inline_keyboard": keyboard}

    def _get_help_text(self) -> str:
        return (
            "🤖 <b>Proxmox VE 监控服务 · Bot 指令指南</b>:\n\n"
            "🎛️ <b>交互式管理中心</b>:\n"
            "• <b>/manage</b> - 呼出核心管理控制面板 (推荐使用)\n"
            "• <b>/start</b> 或 <b>/menu</b> - 进入管理中心\n"
            "• <b>/key_vms</b> 或 <b>/vms</b> - 直达实例重点监控点选面板\n\n"
            "🔍 <b>状态与诊断</b>:\n"
            "• <b>/status</b> - 实时拉取并回复 PVE 状态简报\n"
            "• <b>/temp</b> - 查看 CPU 及 NVMe/硬盘硬件温度快照\n"
            "• <b>/cancel</b> - 强行清空积压待处理消息队列\n\n"
            "⚙️ <b>快捷命令行指令</b>:\n"
            "• /set_cpu &lt;温度&gt; - 修改 CPU 告警温度 (如 /set_cpu 80)\n"
            "• /set_mem &lt;百分比&gt; - 修改内存告警比例 (如 /set_mem 85)\n"
            "• /set_nvme &lt;温度&gt; - 修改 NVMe 告警温度 (如 /set_nvme 65)\n"
            "• /set_key_vms &lt;ID列表&gt; - 批量设置重点监控 (如 /set_key_vms 101,102)\n"
            "• /add_key_vm &lt;ID&gt; / /del_key_vm &lt;ID&gt; - 手动增删监控实例"
        )

    # ==================== Callback Query Handler ====================

    def _handle_callback_query(self, cb_id: str, chat_id: str, msg_id: int, data: str):
        if self.chat_id and str(chat_id) != self.chat_id:
            self._answer_callback(cb_id, "⛔ 未授权的操作")
            return

        # 菜单导航回调
        if data in ["m_manage", "menu_main"]:
            self._answer_callback(cb_id)
            text, reply_markup = self._build_manage_menu()
            self._edit_message(chat_id, msg_id, text, reply_markup=reply_markup)

        elif data in ["m_vms", "menu_vms"]:
            self._answer_callback(cb_id)
            text, reply_markup = self._build_vm_menu()
            self._edit_message(chat_id, msg_id, text, reply_markup=reply_markup)

        elif data == "m_thresholds":
            self._answer_callback(cb_id)
            text, reply_markup = self._build_thresholds_menu()
            self._edit_message(chat_id, msg_id, text, reply_markup=reply_markup)

        elif data == "m_notifiers":
            self._answer_callback(cb_id)
            text, reply_markup = self._build_notifiers_menu()
            self._edit_message(chat_id, msg_id, text, reply_markup=reply_markup)

        elif data == "m_traffic":
            self._answer_callback(cb_id)
            text, reply_markup = self._build_traffic_menu()
            self._edit_message(chat_id, msg_id, text, reply_markup=reply_markup)

        elif data in ["m_help", "menu_help"]:
            self._answer_callback(cb_id)
            help_msg = self._get_help_text()
            keyboard = [[{"text": "🔙 返回管理中心", "callback_data": "m_manage"}]]
            self._edit_message(chat_id, msg_id, help_msg, reply_markup={"inline_keyboard": keyboard})

        elif data in ["m_close", "menu_close"]:
            self._answer_callback(cb_id, "管理中心已关闭")
            self._edit_message(chat_id, msg_id, "❌ <b>管理中心已关闭</b>")

        # 实例监控面板回调
        elif data.startswith("toggle_vm_"):
            try:
                vm_id = int(data.replace("toggle_vm_", ""))
                vm_cfg = self.config.setdefault("thresholds", {}).setdefault("vms", {})
                key_vms = vm_cfg.setdefault("key_vm_ids", [])
                if vm_id in key_vms:
                    key_vms.remove(vm_id)
                    cb_msg = f"已将 [{vm_id}] 移除重点监控"
                else:
                    key_vms.append(vm_id)
                    key_vms.sort()
                    cb_msg = f"已将 [{vm_id}] 加入重点监控"
                self._save_config_and_reload(self.config)
                self._answer_callback(cb_id, cb_msg)
                text, reply_markup = self._build_vm_menu()
                self._edit_message(chat_id, msg_id, text, reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"处理 toggle_vm callback 失败: {e}")
                self._answer_callback(cb_id, "操作失败")

        elif data == "vm_action_toggle_alert":
            vm_cfg = self.config.setdefault("thresholds", {}).setdefault("vms", {})
            curr = vm_cfg.get("alert_on_stopped", True)
            vm_cfg["alert_on_stopped"] = not curr
            self._save_config_and_reload(self.config)
            cb_msg = "实例停机告警已关闭" if curr else "实例停机告警已开启"
            self._answer_callback(cb_id, cb_msg)
            text, reply_markup = self._build_vm_menu()
            self._edit_message(chat_id, msg_id, text, reply_markup=reply_markup)

        elif data == "vm_action_clear":
            self.config.setdefault("thresholds", {}).setdefault("vms", {})["key_vm_ids"] = []
            self._save_config_and_reload(self.config)
            self._answer_callback(cb_id, "已重置为监控全部实例")
            text, reply_markup = self._build_vm_menu()
            self._edit_message(chat_id, msg_id, text, reply_markup=reply_markup)

        # 阈值调整回调
        elif data.startswith("th_"):
            parts = data.split("_")
            metric = parts[1]
            delta = int(parts[2])
            th_cfg = self.config.setdefault("thresholds", {})
            if metric == "cpu":
                curr = th_cfg.setdefault("temperature", {}).get("cpu_warning", 75)
                new_val = max(40, min(100, curr + delta))
                th_cfg["temperature"]["cpu_warning"] = new_val
                cb_msg = f"CPU 告警调整为 {new_val}°C"
            elif metric == "nvme":
                curr = th_cfg.setdefault("temperature", {}).get("nvme_warning", 60)
                new_val = max(40, min(90, curr + delta))
                th_cfg["temperature"]["nvme_warning"] = new_val
                cb_msg = f"NVMe 告警调整为 {new_val}°C"
            elif metric == "mem":
                curr = th_cfg.setdefault("memory", {}).get("usage_percent_warning", 90)
                new_val = max(50, min(99, curr + delta))
                th_cfg["memory"]["usage_percent_warning"] = new_val
                cb_msg = f"内存预警调整为 {new_val}%"
            else:
                cb_msg = "未知调整项"

            self._save_config_and_reload(self.config)
            self._answer_callback(cb_id, cb_msg)
            text, reply_markup = self._build_thresholds_menu()
            self._edit_message(chat_id, msg_id, text, reply_markup=reply_markup)

        # 通知渠道控制回调
        elif data == "n_tg_briefing":
            tg_cfg = self.config.setdefault("notifiers", {}).setdefault("telegram", {})
            curr = tg_cfg.get("briefing_enabled", True)
            tg_cfg["briefing_enabled"] = not curr
            self._save_config_and_reload(self.config)
            self.app.notifier_mgr._init_notifiers()
            cb_msg = "TG 定时简报已关闭" if curr else "TG 定时简报已开启"
            self._answer_callback(cb_id, cb_msg)
            text, reply_markup = self._build_notifiers_menu()
            self._edit_message(chat_id, msg_id, text, reply_markup=reply_markup)

        elif data == "n_email":
            email_cfg = self.config.setdefault("notifiers", {}).setdefault("email", {})
            curr = email_cfg.get("enabled", False)
            email_cfg["enabled"] = not curr
            self._save_config_and_reload(self.config)
            self.app.notifier_mgr._init_notifiers()
            cb_msg = "邮件通知已关闭" if curr else "邮件通知已开启"
            self._answer_callback(cb_id, cb_msg)
            text, reply_markup = self._build_notifiers_menu()
            self._edit_message(chat_id, msg_id, text, reply_markup=reply_markup)

        elif data == "n_alert_engine":
            alert_interval = self.config.setdefault("schedule", {}).get("alert_interval_seconds", 120)
            if alert_interval > 0:
                self.config.setdefault("schedule", {})["alert_interval_seconds"] = 0
                new_sec = 0
                cb_msg = "告警引擎已暂停"
            else:
                self.config.setdefault("schedule", {})["alert_interval_seconds"] = 120
                new_sec = 120
                cb_msg = "告警引擎已恢复"
            self._save_config_and_reload(self.config)
            self.app.update_alert_job_interval(new_sec)
            self._answer_callback(cb_id, cb_msg)
            text, reply_markup = self._build_notifiers_menu()
            self._edit_message(chat_id, msg_id, text, reply_markup=reply_markup)

        # 流量维度回调
        elif data.startswith("tr_"):
            dim = data.replace("tr_", "")
            key_map = {"daily": "show_daily", "weekly": "show_weekly", "monthly": "show_monthly", "total": "show_total"}
            if dim in key_map:
                key = key_map[dim]
                tr_cfg = self.config.setdefault("traffic", {})
                curr = tr_cfg.get(key, True)
                tr_cfg[key] = not curr
                self._save_config_and_reload(self.config)
                cb_msg = f"流量统计已{'关闭' if curr else '开启'}"
                self._answer_callback(cb_id, cb_msg)
                text, reply_markup = self._build_traffic_menu()
                self._edit_message(chat_id, msg_id, text, reply_markup=reply_markup)

        # 命令动作回调
        elif data == "cmd_status":
            self._answer_callback(cb_id, "正在实时拉取简报...")
            try:
                brief_data = self.app.generate_briefing()
                keyboard = [[{"text": "🔙 返回管理中心", "callback_data": "m_manage"}]]
                self._send_reply(chat_id, brief_data["tg_html"], parse_mode="HTML", reply_markup={"inline_keyboard": keyboard})
            except Exception as e:
                self._send_reply(chat_id, f"❌ 采集过程出错: {e}")

        elif data == "cmd_temp":
            self._answer_callback(cb_id)
            self._handle_command(chat_id, "/temp")

    # ==================== Command Handler ====================

    def _handle_command(self, chat_id: str, text: str):
        if self.chat_id and str(chat_id) != self.chat_id:
            logger.warning(f"拒绝未经授权的 Telegram 交互请求, Chat ID: {chat_id}")
            self._send_reply(chat_id, "⛔ 未授权的 Chat ID，拒绝操作。")
            return

        cmd_parts = text.strip().split()
        cmd = cmd_parts[0].lower()

        if cmd in ["/manage", "/start", "/menu"]:
            text, reply_markup = self._build_manage_menu()
            self._send_reply(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)

        elif cmd in ["/help"]:
            help_msg = self._get_help_text()
            keyboard = [[{"text": "🔙 返回管理中心", "callback_data": "m_manage"}]]
            self._send_reply(chat_id, help_msg, parse_mode="HTML", reply_markup={"inline_keyboard": keyboard})

        elif cmd in ["/key_vms", "/get_key_vms", "/vms", "/edit_vms"]:
            text, reply_markup = self._build_vm_menu()
            self._send_reply(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)

        elif cmd in ["/cancel", "/clear", "/stop_queue"]:
            self.last_status_time = 0
            self._flush_old_updates()
            self._send_reply(
                chat_id,
                "🧹 <b>已成功清空 Telegram 待处理消息队列！</b>\n"
                "所有积压的历史指令已丢弃，频控限制已解开，Bot 已恢复全新就绪状态。",
                parse_mode="HTML"
            )

        elif cmd in ["/status", "/pve"]:
            now = time.time()
            if now - self.last_status_time < 15:
                self._send_reply(chat_id, "⚠️ 简报生成请求过于频繁，请稍后再试。", parse_mode="HTML")
                return
            self.last_status_time = now
            self._send_reply(chat_id, "🔄 正在为您实时采集 PVE 节点数据，请稍候...", parse_mode="HTML")
            try:
                brief_data = self.app.generate_briefing()
                keyboard = [[{"text": "🔙 返回管理中心", "callback_data": "m_manage"}]]
                self._send_reply(chat_id, brief_data["tg_html"], parse_mode="HTML", reply_markup={"inline_keyboard": keyboard})
            except Exception as e:
                self._send_reply(chat_id, f"❌ 采集过程出错: {e}", parse_mode="HTML")

        elif cmd in ["/temp", "/temperature"]:
            try:
                temps = self.app.hw_collector.get_temperatures()
                lines = ["🌡️ <b>实时硬件温度</b>"]

                cpu_temp = temps.get("cpu_temp")
                lines.append(
                    f"• CPU Package: <code>{cpu_temp:.1f}°C</code>"
                    if isinstance(cpu_temp, (int, float))
                    else "• CPU Package: <code>未检测到</code>"
                )

                cpu_cores = temps.get("cpu_cores", [])
                if cpu_cores:
                    core_values = " / ".join(f"{value:.1f}°C" for value in cpu_cores)
                    lines.append(f"• CPU 核心: <code>{core_values}</code>")

                for label, key in [("NVMe", "nvme_temps"), ("硬盘", "hdd_temps")]:
                    devices = temps.get(key, {})
                    if devices:
                        values = "；".join(
                            f"{name}: {value:.1f}°C"
                            for name, value in devices.items()
                            if isinstance(value, (int, float))
                        )
                        if values:
                            lines.append(f"• {label}: <code>{values}</code>")

                lines.append("\n<i>温度为当前快照，PVE RRD 不提供 24h 温度历史。</i>")
                keyboard = [[{"text": "🔙 返回管理中心", "callback_data": "m_manage"}]]
                self._send_reply(chat_id, "\n".join(lines), parse_mode="HTML", reply_markup={"inline_keyboard": keyboard})
            except Exception as e:
                logger.error(f"实时温度采集失败: {e}")
                self._send_reply(chat_id, "❌ 温度采集失败，请检查容器的传感器访问权限。", parse_mode="HTML")

        elif cmd == "/toggle_daily":
            tr_cfg = self.config.setdefault("traffic", {})
            curr = tr_cfg.get("show_daily", True)
            tr_cfg["show_daily"] = not curr
            self._save_config_and_reload(self.config)
            status_str = "🟢 已开启" if not curr else "🔴 已关闭"
            self._send_reply(chat_id, f"🌐 <b>流量维度变更</b>: 24h 日流量统计已切换为 <b>{status_str}</b>！", parse_mode="HTML")

        elif cmd == "/toggle_weekly":
            tr_cfg = self.config.setdefault("traffic", {})
            curr = tr_cfg.get("show_weekly", True)
            tr_cfg["show_weekly"] = not curr
            self._save_config_and_reload(self.config)
            status_str = "🟢 已开启" if not curr else "🔴 已关闭"
            self._send_reply(chat_id, f"🌐 <b>流量维度变更</b>: 7d 周流量统计已切换为 <b>{status_str}</b>！", parse_mode="HTML")

        elif cmd == "/toggle_monthly":
            tr_cfg = self.config.setdefault("traffic", {})
            curr = tr_cfg.get("show_monthly", True)
            tr_cfg["show_monthly"] = not curr
            self._save_config_and_reload(self.config)
            status_str = "🟢 已开启" if not curr else "🔴 已关闭"
            self._send_reply(chat_id, f"🌐 <b>流量维度变更</b>: 30d 月流量统计已切换为 <b>{status_str}</b>！", parse_mode="HTML")

        elif cmd == "/toggle_total":
            tr_cfg = self.config.setdefault("traffic", {})
            curr = tr_cfg.get("show_total", True)
            tr_cfg["show_total"] = not curr
            self._save_config_and_reload(self.config)
            status_str = "🟢 已开启" if not curr else "🔴 已关闭"
            self._send_reply(chat_id, f"🌐 <b>流量维度变更</b>: 开机累计总流量统计已切换为 <b>{status_str}</b>！", parse_mode="HTML")

        elif cmd in ["/toggle_briefing", "/toggle_tg_briefing"]:
            tg_cfg = self.config.setdefault("notifiers", {}).setdefault("telegram", {})
            curr = tg_cfg.get("briefing_enabled", True)
            tg_cfg["briefing_enabled"] = not curr
            self._save_config_and_reload(self.config)
            self.app.notifier_mgr._init_notifiers()
            status_str = "🟢 已开启" if not curr else "🔴 已关闭"
            self._send_reply(chat_id, f"🔔 <b>通知开关变更</b>: Telegram 定时简报推送已切换为 <b>{status_str}</b>！", parse_mode="HTML")

        elif cmd == "/toggle_email":
            email_cfg = self.config.setdefault("notifiers", {}).setdefault("email", {})
            curr = email_cfg.get("enabled", False)
            email_cfg["enabled"] = not curr
            self._save_config_and_reload(self.config)
            self.app.notifier_mgr._init_notifiers()
            status_str = "🟢 已开启" if not curr else "🔴 已关闭"
            self._send_reply(chat_id, f"🔔 <b>通知开关变更</b>: 邮件通知已切换为 <b>{status_str}</b>！", parse_mode="HTML")

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
            self._send_reply(chat_id, f"⚠️ <b>告警引擎状态</b>: 异常告警已切换为 <b>{status_str}</b>！", parse_mode="HTML")

        elif cmd == "/set_cpu":
            if len(cmd_parts) > 1 and cmd_parts[1].isdigit():
                val = int(cmd_parts[1])
                self.config.setdefault("thresholds", {}).setdefault("temperature", {})["cpu_warning"] = val
                self._save_config_and_reload(self.config)
                self._send_reply(chat_id, f"✅ <b>成功调整参数</b>: CPU 告警阈值已修改为 <b>{val}°C</b>！", parse_mode="HTML")
            else:
                self._send_reply(chat_id, "⚠️ 格式错误，用法示例: <code>/set_cpu 80</code>", parse_mode="HTML")

        elif cmd == "/set_mem":
            if len(cmd_parts) > 1 and cmd_parts[1].isdigit():
                val = int(cmd_parts[1])
                self.config.setdefault("thresholds", {}).setdefault("memory", {})["usage_percent_warning"] = val
                self._save_config_and_reload(self.config)
                self._send_reply(chat_id, f"✅ <b>成功调整参数</b>: 物理内存告警阈值已修改为 <b>{val}%</b>！", parse_mode="HTML")
            else:
                self._send_reply(chat_id, "⚠️ 格式错误，用法示例: <code>/set_mem 85</code>", parse_mode="HTML")

        elif cmd == "/set_nvme":
            if len(cmd_parts) > 1 and cmd_parts[1].isdigit():
                val = int(cmd_parts[1])
                self.config.setdefault("thresholds", {}).setdefault("temperature", {})["nvme_warning"] = val
                self._save_config_and_reload(self.config)
                self._send_reply(chat_id, f"✅ <b>成功调整参数</b>: NVMe 告警阈值已修改为 <b>{val}°C</b>！", parse_mode="HTML")
            else:
                self._send_reply(chat_id, "⚠️ 格式错误，用法示例: <code>/set_nvme 65</code>", parse_mode="HTML")

        elif cmd in ["/toggle_vm_alert", "/toggle_vms"]:
            vm_cfg = self.config.setdefault("thresholds", {}).setdefault("vms", {})
            curr = vm_cfg.get("alert_on_stopped", True)
            vm_cfg["alert_on_stopped"] = not curr
            self._save_config_and_reload(self.config)
            status_str = "🟢 已开启" if not curr else "🔴 已关闭"
            self._send_reply(chat_id, f"🖥️ <b>告警设置变更</b>: 虚拟机/容器停机告警已切换为 <b>{status_str}</b>！", parse_mode="HTML")

        elif cmd == "/set_key_vms":
            if len(cmd_parts) > 1:
                raw_arg = " ".join(cmd_parts[1:])
                if raw_arg.lower() in ["none", "clear", "all", "空", "清空"]:
                    new_vms = []
                else:
                    items = raw_arg.replace(",", " ").split()
                    new_vms = [int(x) for x in items if x.isdigit()]
                self.config.setdefault("thresholds", {}).setdefault("vms", {})["key_vm_ids"] = new_vms
                self._save_config_and_reload(self.config)
                vms_str = ", ".join(str(x) for x in new_vms) if new_vms else "全部实例 (默认监控所有)"
                self._send_reply(chat_id, f"✅ <b>成功调整参数</b>: 重点监控实例列表已更新为: <code>{vms_str}</code>！", parse_mode="HTML")
            else:
                self._send_reply(chat_id, "⚠️ 格式错误，用法示例: <code>/set_key_vms 101,102</code> 或 <code>/set_key_vms clear</code> 清空列表", parse_mode="HTML")

        elif cmd == "/add_key_vm":
            if len(cmd_parts) > 1 and cmd_parts[1].isdigit():
                val = int(cmd_parts[1])
                vm_cfg = self.config.setdefault("thresholds", {}).setdefault("vms", {})
                key_vms = vm_cfg.setdefault("key_vm_ids", [])
                if val not in key_vms:
                    key_vms.append(val)
                    key_vms.sort()
                    self._save_config_and_reload(self.config)
                    self._send_reply(chat_id, f"✅ <b>成功添加</b>: 实例 <code>{val}</code> 已加入重点监控列表！当前列表: <code>{key_vms}</code>", parse_mode="HTML")
                else:
                    self._send_reply(chat_id, f"ℹ️ 实例 <code>{val}</code> 已在重点监控列表中。", parse_mode="HTML")
            else:
                self._send_reply(chat_id, "⚠️ 格式错误，用法示例: <code>/add_key_vm 101</code>", parse_mode="HTML")

        elif cmd == "/del_key_vm":
            if len(cmd_parts) > 1 and cmd_parts[1].isdigit():
                val = int(cmd_parts[1])
                vm_cfg = self.config.setdefault("thresholds", {}).setdefault("vms", {})
                key_vms = vm_cfg.get("key_vm_ids", [])
                if val in key_vms:
                    key_vms.remove(val)
                    self._save_config_and_reload(self.config)
                    vms_str = ", ".join(str(x) for x in key_vms) if key_vms else "全部实例 (默认监控所有)"
                    self._send_reply(chat_id, f"✅ <b>成功移除</b>: 实例 <code>{val}</code> 已从重点监控列表移除！当前列表: <code>{vms_str}</code>", parse_mode="HTML")
                else:
                    self._send_reply(chat_id, f"ℹ️ 实例 <code>{val}</code> 不在重点监控列表中。", parse_mode="HTML")
            else:
                self._send_reply(chat_id, "⚠️ 格式错误，用法示例: <code>/del_key_vm 103</code>", parse_mode="HTML")

    def _poll_updates(self):
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        while self.running:
            try:
                resp = requests.get(url, params={"offset": self.offset, "timeout": 10}, timeout=15)
                if resp.status_code == 200:
                    updates = resp.json().get("result", [])
                    for update in updates:
                        self.offset = update["update_id"] + 1

                        # 1. 响应按钮点击 (callback_query)
                        if "callback_query" in update:
                            cb = update["callback_query"]
                            cb_id = cb.get("id")
                            msg = cb.get("message", {})
                            chat_id = msg.get("chat", {}).get("id")
                            msg_id = msg.get("message_id")
                            data = cb.get("data", "")
                            if chat_id and data:
                                threading.Thread(
                                    target=self._handle_callback_query,
                                    args=(cb_id, chat_id, msg_id, data),
                                    daemon=True
                                ).start()
                            continue

                        # 2. 响应文本消息指令 (message)
                        msg = update.get("message", {})
                        msg_date = msg.get("date", 0)
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
