import glob
import json
import logging
import os
import subprocess

logger = logging.getLogger("pveMonitor.collectors.hardware")

class HardwareCollector:
    """硬件温度、S.M.A.R.T 磁盘寿命与 UPS 状态采集器"""

    def __init__(self, config: dict):
        self.config = config

    def get_temperatures(self) -> dict:
        """获取 CPU、NVMe 和 硬盘温度 (以摄氏度 °C 为单位)"""
        temps = {
            "cpu_temp": None,
            "cpu_cores": [],
            "nvme_temps": {},
            "hdd_temps": {}
        }
        
        # 1. 尝试使用 sensors -j 命令 (如果系统中安装了 lm-sensors)
        try:
            res = subprocess.run(["sensors", "-j"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout:
                sensor_data = json.loads(res.stdout)
                core_temps = []
                for chip_name, chip_val in sensor_data.items():
                    # CPU Core/Package 温度
                    if "coretemp" in chip_name or "k10temp" in chip_name or "zenpower" in chip_name:
                        for k, v in chip_val.items():
                            if isinstance(v, dict):
                                for prop_k, prop_v in v.items():
                                    if "input" in prop_k:
                                        if "Package" in k or "Tdie" in k or "Tctl" in k:
                                            temps["cpu_temp"] = round(float(prop_v), 1)
                                        elif "Core" in k:
                                            core_temps.append(round(float(prop_v), 1))
                    # NVMe 温度
                    elif "nvme" in chip_name:
                        for k, v in chip_val.items():
                            if isinstance(v, dict):
                                for prop_k, prop_v in v.items():
                                    if "input" in prop_k and ("Composite" in k or "Sensor 1" in k):
                                        temps["nvme_temps"][chip_name] = round(float(prop_v), 1)

                if core_temps and temps["cpu_temp"] is None:
                    temps["cpu_temp"] = round(sum(core_temps) / len(core_temps), 1)
                temps["cpu_cores"] = core_temps
                return temps
        except Exception:
            pass # 无法运行 sensors，退化到读取 sysfs

        # 2. 从 Linux sysfs 读取 (/sys/class/thermal/ 及 /sys/class/hwmon/)
        try:
            thermal_zones = glob.glob("/sys/class/thermal/thermal_zone*")
            for zone in thermal_zones:
                type_file = os.path.join(zone, "type")
                temp_file = os.path.join(zone, "temp")
                if os.path.exists(type_file) and os.path.exists(temp_file):
                    with open(type_file, "r") as tf, open(temp_file, "r") as pf:
                        z_type = tf.read().strip()
                        raw_temp = float(pf.read().strip()) / 1000.0
                        if "x86_pkg_temp" in z_type or "acpitz" in z_type or "cpu" in z_type.lower():
                            if temps["cpu_temp"] is None or raw_temp > temps["cpu_temp"]:
                                temps["cpu_temp"] = round(raw_temp, 1)
        except Exception as e:
            logger.warning(f"从 sysfs 读取温度失败: {e}")

        # 3. 如果本地无法获取且开启了 SSH 硬件读取 (远程连接到 PVE 节点)
        ssh_cfg = self.config.get("ssh_hardware", {})
        if temps["cpu_temp"] is None and ssh_cfg.get("enabled", False):
            try:
                import paramiko
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(
                    ssh_cfg.get("host"),
                    port=ssh_cfg.get("port", 22),
                    username=ssh_cfg.get("user", "root"),
                    password=ssh_cfg.get("password", ""),
                    timeout=5
                )
                cmd = "for z in /sys/class/thermal/thermal_zone*; do if [ -f \"$z/temp\" ] && [ -f \"$z/type\" ]; then echo \"$(cat $z/type): $(cat $z/temp)\"; fi; done"
                _, stdout, _ = client.exec_command(cmd)
                output = stdout.read().decode("utf-8").strip()
                for line in output.splitlines():
                    if ":" in line:
                        t_type, t_val = line.split(":", 1)
                        c_val = round(float(t_val.strip()) / 1000.0, 1)
                        if "x86_pkg_temp" in t_type or "acpitz" in t_type or "cpu" in t_type.lower():
                            if temps["cpu_temp"] is None or c_val > temps["cpu_temp"]:
                                temps["cpu_temp"] = c_val
                client.close()
            except Exception as e:
                logger.warning(f"通过 SSH 远程获取 PVE 温度失败: {e}")

        return temps

    def get_smart_health(self) -> list:
        """获取 NVMe/HDD 磁盘 S.M.A.R.T 健康度与剩余寿命 (Wearout)"""
        disks_info = []
        try:
            # 扫描 /dev/sd* 和 /dev/nvme*
            disk_paths = glob.glob("/dev/sd[a-z]") + glob.glob("/dev/nvme[0-9]n[0-9]")
            for disk in disk_paths:
                cmd = ["smartctl", "-A", "-j", disk]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
                if res.returncode in [0, 4] and res.stdout:
                    data = json.loads(res.stdout)
                    info = {
                        "device": os.path.basename(disk),
                        "model": data.get("model_name", "Unknown"),
                        "smart_passed": data.get("smart_status", {}).get("passed", True),
                        "wearout_remaining": None,
                        "temperature": data.get("temperature", {}).get("current")
                    }
                    
                    # NVMe 剩余寿命 (Percentage Used -> Wearout = 100 - Used)
                    nvme_health = data.get("nvme_smart_health_information_log", {})
                    if "percentage_used" in nvme_health:
                        used = nvme_health["percentage_used"]
                        info["wearout_remaining"] = max(0, 100 - used)
                        
                    disks_info.append(info)
        except Exception as e:
            logger.debug(f"Smartctl 无法获取磁盘状态: {e}")

        return disks_info

    def get_ups_status(self) -> dict:
        """获取 UPS 状态 (若安装了 nut apcupsd)"""
        ups_info = {"connected": False, "status": "Unknown", "battery_charge": None, "load_percent": None}
        try:
            res = subprocess.run(["upsc", "myups@localhost"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                ups_info["connected"] = True
                for line in res.stdout.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        k, v = k.strip(), v.strip()
                        if k == "ups.status":
                            ups_info["status"] = v
                        elif k == "battery.charge":
                            ups_info["battery_charge"] = float(v)
                        elif k == "ups.load":
                            ups_info["load_percent"] = float(v)
        except Exception:
            pass
        return ups_info

    def collect_from_pve_collector(self, pve_collector) -> list:
        """纯 PVE REST API 模式获取磁盘与 SMART 健康度 (100% 免 SSH)"""
        disks_info = []
        try:
            raw_disks = pve_collector.get_disks_list()
            if isinstance(raw_disks, list):
                for d in raw_disks:
                    if isinstance(d, dict):
                        dev = d.get("devpath") or d.get("name", "Unknown")
                        model = d.get("model", "Disk")
                        health = d.get("health", "PASSED")
                        wearout = d.get("wearout")
                        disks_info.append({
                            "device": dev,
                            "model": model,
                            "smart_passed": health == "PASSED",
                            "wearout_remaining": wearout,
                            "health": health
                        })
        except Exception as e:
            logger.warning(f"通过 PVE API 获取磁盘 SMART 失败: {e}")

        return disks_info

    def collect_all(self, pve_collector=None) -> dict:
        """收集硬件相关的所有状态"""
        local_temps = self.get_temperatures()
        smart_info = self.get_smart_health()

        # 如果本地未安装 smartctl 或者在 Docker 中免 SSH 运行，自动从 PVE REST API 补充磁盘 SMART 与寿命
        if not smart_info and pve_collector:
            smart_info = self.collect_from_pve_collector(pve_collector)

        return {
            "temperatures": local_temps,
            "disks_smart": smart_info,
            "ups": self.get_ups_status()
        }
