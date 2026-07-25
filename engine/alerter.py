import datetime
import json
import logging
import os

logger = logging.getLogger("pveMonitor.engine.alerter")

HISTORY_FILE = "logs/alert_history.json"

class AlertEngine:
    """即时异常预警规则评估引擎 (包含防刷屏 Cooling 冷却机制，持久化记录跨重启)"""

    def __init__(self, config: dict, history_file: str = HISTORY_FILE):
        self.config = config
        self.thresholds = config.get("thresholds", {})
        self.cooldown_minutes = config.get("alert_cooldown_minutes", 60)
        self.history_file = history_file
        
        # 记录已触发告警的上次发送时间 { alert_key: datetime }
        self._alert_history = {}
        self._load_history()

    def _load_history(self):
        """从持久化文件加载告警历史"""
        if not self.history_file or not os.path.exists(self.history_file) or os.path.getsize(self.history_file) == 0:
            return
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    self._alert_history[k] = datetime.datetime.fromisoformat(v)
        except Exception as e:
            logger.warning(f"读取告警历史记录失败: {e}")

    def _save_history(self):
        """将告警历史持久化至 JSON 文件"""
        if not self.history_file:
            return
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            data = {k: v.isoformat() for k, v in self._alert_history.items()}
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存告警历史记录失败: {e}")

    def _is_in_cooldown(self, alert_key: str) -> bool:
        """检查特定规则告警是否尚处于冷却时间内"""
        if alert_key not in self._alert_history:
            return False
        last_time = self._alert_history[alert_key]
        elapsed = (datetime.datetime.now() - last_time).total_seconds() / 60.0
        return elapsed < self.cooldown_minutes

    def _mark_alerted(self, alert_key: str):
        """记录告警触发时间并持久化"""
        self._alert_history[alert_key] = datetime.datetime.now()
        self._save_history()

    def check_alerts(self, api_data: dict, hw_data: dict, health_data: dict) -> list:
        """根据最新监控数据评估告警规则，返回待触发的告警列表"""
        alerts = []
        
        # 1. 检查 CPU / NVMe 温度
        temp_th = self.thresholds.get("temperature", {})
        cpu_warning_th = temp_th.get("cpu_warning", 75)
        nvme_warning_th = temp_th.get("nvme_warning", 60)
        
        temps = hw_data.get("temperatures", {})
        cpu_temp = temps.get("cpu_temp")
        if cpu_temp and isinstance(cpu_temp, (int, float)) and cpu_temp >= cpu_warning_th:
            key = "cpu_temp_high"
            if not self._is_in_cooldown(key):
                alerts.append({
                    "key": key,
                    "title": "CPU 温度过高警报",
                    "content": f"🔥 当前 CPU 温度已达到 **{cpu_temp}°C** (设定的预警阈值为 {cpu_warning_th}°C)，请检查散热风扇或清灰！"
                })
                self._mark_alerted(key)

        for nvme_name, nvme_t in temps.get("nvme_temps", {}).items():
            if nvme_t and nvme_t >= nvme_warning_th:
                key = f"nvme_temp_high_{nvme_name}"
                if not self._is_in_cooldown(key):
                    alerts.append({
                        "key": key,
                        "title": "NVMe 固态硬盘过热",
                        "content": f"🔥 固态硬盘 [{nvme_name}] 温度达到 **{nvme_t}°C** (阈值 {nvme_warning_th}°C)。"
                    })
                    self._mark_alerted(key)

        # 2. 检查内存与 Swap 占用率
        mem_th = self.thresholds.get("memory", {})
        mem_warning_th = mem_th.get("usage_percent_warning", 90)
        swap_warning_th = mem_th.get("swap_percent_warning", 50)
        
        node_stat = api_data.get("node_status", {})
        mem_total = node_stat.get("memory", {}).get("total", 0)
        mem_used = node_stat.get("memory", {}).get("used", 0)
        if mem_total > 0:
            mem_pct = (mem_used / mem_total) * 100
            if mem_pct >= mem_warning_th:
                key = "memory_high"
                if not self._is_in_cooldown(key):
                    alerts.append({
                        "key": key,
                        "title": "物理内存吃紧预警",
                        "content": f"🧠 宿主机内存占用已达到 **{mem_pct:.1f}%** ({mem_used/(1024**3):.1f}GB / {mem_total/(1024**3):.1f}GB)。"
                    })
                    self._mark_alerted(key)

        swap_total = node_stat.get("swap", {}).get("total", 0)
        swap_used = node_stat.get("swap", {}).get("used", 0)
        if swap_total > 0:
            swap_pct = (swap_used / swap_total) * 100
            if swap_pct >= swap_warning_th:
                key = "swap_high"
                if not self._is_in_cooldown(key):
                    alerts.append({
                        "key": key,
                        "title": "Swap 交换空间高占用预警",
                        "content": f"💾 宿主机 Swap 占用率已达到 **{swap_pct:.1f}%** ({swap_used/(1024**3):.1f}GB / {swap_total/(1024**3):.1f}GB)，可能存在内存开销过大。"
                    })
                    self._mark_alerted(key)

        # 3. 检查关键虚拟机/容器离线状态
        vm_th = self.thresholds.get("vms", {})
        if vm_th.get("alert_on_stopped", True):
            key_vms = vm_th.get("key_vm_ids", [])
            all_guests = api_data.get("vms", []) + api_data.get("lxcs", [])
            for g in all_guests:
                g_id = g.get("vmid") or g.get("id")
                g_name = g.get("name", "Unknown")
                g_status = g.get("status")
                
                if (not key_vms or g_id in key_vms) and g_status != "running":
                    key = f"vm_stopped_{g_id}"
                    if not self._is_in_cooldown(key):
                        alerts.append({
                            "key": key,
                            "title": f"关键虚拟机/容器离线 [{g_id}]",
                            "content": f"🔴 重点监控的实例 **[{g_id}] {g_name}** 当前处于停机状态 (`{g_status}`)！"
                        })
                        self._mark_alerted(key)

        # 4. 检查最近 OOM 内存溢出日志
        oom_events = health_data.get("recent_oom_events", [])
        if oom_events:
            key = "oom_event_detected"
            if not self._is_in_cooldown(key):
                alerts.append({
                    "key": key,
                    "title": "系统触发 OOM 内存溢出",
                    "content": f"⚠️ 系统近 10 分钟内触发了 Linux OOM Killer 杀进程事件：\n`{oom_events[0]}`"
                })
                self._mark_alerted(key)

        return alerts
