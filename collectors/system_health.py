import logging
import os
import subprocess
import time

logger = logging.getLogger("pveMonitor.collectors.system_health")

class SystemHealthCollector:
    """System health diagnostics, network ping reachability, and OOM event scanner."""

    def __init__(self, config: dict):
        self.config = config

    def check_ping(self, host: str, count: int = 1) -> bool:
        """Check network ping reachability to a host or guest IP."""
        param = "-n" if os.name == "nt" else "-c"
        cmd = ["ping", param, str(count), "-w", "2", host]
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=3)
            return res.returncode == 0
        except Exception:
            return False

    def scan_recent_oom_events(self, minutes: int = 10) -> list:
        """Scan system journal for recent Linux kernel Out-Of-Memory (OOM) killer events."""
        oom_events = []
        try:
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
        """Collect host system and kernel log events."""
        return {
            "recent_oom_events": self.scan_recent_oom_events(minutes=10)
        }
