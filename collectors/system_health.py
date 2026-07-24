import logging
import os
import subprocess
import time

logger = logging.getLogger("pveMonitor.collectors.system_health")

class SystemHealthCollector:
    """系统健康度、网络 Ping 连通性、OOM 扫描收集器"""

    def __init__(self, config: dict):
        self.config = config

    def check_ping(self, host: str, count: int = 1) -> bool:
        """检查网络主机或 VM IP 的 Ping 连通性"""
        param = "-n" if os.name == "nt" else "-c"
        cmd = ["ping", param, str(count), "-w", "2", host]
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=3)
            return res.returncode == 0
        except Exception:
            return False

    def scan_recent_oom_events(self, minutes: int = 10) -> list:
        """检查系统最近是否发生内存溢出 (Out of Memory / OOM Killer)"""
        oom_events = []
        try:
            # 尝试通过 journalctl 搜索最近的 OOM 记录
            cmd = ["journalctl", f"--since={minutes} min ago", "-k", "-g", "Out of memory|killed process"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout:
                for line in res.stdout.splitlines():
                    if "Out of memory" in line or "Killed process" in line:
                        oom_events.append(line.strip())
        except Exception:
            pass
        return oom_events

    def collect_all(self) -> dict:
        """收集系统与日志级别状态"""
        return {
            "recent_oom_events": self.scan_recent_oom_events(minutes=10)
        }
