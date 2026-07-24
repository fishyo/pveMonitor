import logging
import urllib3
import requests

# 禁用未验证 HTTPS 请求的警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("pveMonitor.collectors.pve_api")

class PVECollector:
    """Proxmox VE REST API 数据采集器"""
    
    def __init__(self, config: dict):
        self.config = config.get("pve", {})
        self.host = self.config.get("host", "localhost")
        self.port = self.config.get("port", 8006)
        self.node_name = self.config.get("node_name", "pve")
        self.verify_ssl = self.config.get("verify_ssl", False)
        self.base_url = f"https://{self.host}:{self.port}/api2/json"
        
        self.auth_type = self.config.get("auth_type", "token")
        self.headers = {}
        self.cookies = {}
        
        self._setup_auth()

    def _setup_auth(self):
        """配置认证 Token 或登录凭证"""
        if self.auth_type == "token":
            user = self.config.get("user", "")
            token_id = self.config.get("token_id", "")
            token_secret = self.config.get("token_secret", "")
            auth_header = f"PVEAPIToken={user}!{token_id}={token_secret}"
            self.headers["Authorization"] = auth_header
            logger.info("已配置 PVE API Token 认证")
        else:
            # 密码认证模式
            self._login_with_password()

    def _login_with_password(self):
        """使用用户名和密码获取 CSRFPreventionToken 和 PVEAuthCookie"""
        user = self.config.get("user", "root@pam")
        password = self.config.get("password", "")
        login_url = f"{self.base_url}/access/ticket"
        try:
            resp = requests.post(
                login_url,
                data={"username": user, "password": password},
                verify=self.verify_ssl,
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            ticket = data.get("ticket")
            csrf = data.get("CSRFPreventionToken")
            self.cookies["PVEAuthCookie"] = ticket
            self.headers["CSRFPreventionToken"] = csrf
            logger.info("PVE 密码登录认证成功")
        except Exception as e:
            logger.error(f"PVE 密码登录认证失败: {e}")

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """通用 GET API 请求包装"""
        url = f"{self.base_url}{endpoint}"
        try:
            resp = requests.get(
                url,
                headers=self.headers,
                cookies=self.cookies,
                params=params,
                verify=self.verify_ssl,
                timeout=10
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except Exception as e:
            logger.error(f"请求 PVE API 失败 [{endpoint}]: {e}")
            return {}

    def get_node_status(self) -> dict:
        """获取节点综合状态 (内存, CPU, Swap, Uptime, KSM)"""
        return self._get(f"/nodes/{self.node_name}/status")

    def get_node_rrddata(self, timeframe: str = "day") -> list:
        """获取节点历史 RRD 数据 (网络流量 netin/netout, 磁盘读写 diskread/diskwrite)"""
        return self._get(f"/nodes/{self.node_name}/rrddata", params={"timeframe": timeframe})

    def get_vms_status(self) -> list:
        """获取 QEMU 虚拟机列表及状态"""
        return self._get(f"/nodes/{self.node_name}/qemu")

    def get_lxcs_status(self) -> list:
        """获取 LXC 容器列表及状态"""
        return self._get(f"/nodes/{self.node_name}/lxc")

    def get_storage_status(self) -> list:
        """获取存储池状态与容量"""
        return self._get(f"/nodes/{self.node_name}/storage")

    def get_recent_tasks(self, limit: int = 20) -> list:
        """获取近期节点任务列表 (用于检测备份 VZDump 执行结果)"""
        return self._get(f"/nodes/{self.node_name}/tasks", params={"limit": limit})

    def get_disks_list(self) -> list:
        """获取物理磁盘与 S.M.A.R.T 健康列表 (免 SSH)"""
        return self._get(f"/nodes/{self.node_name}/disks/list")

    def get_vm_rrddata(self, vmid: int, timeframe: str = "day") -> list:
        """获取指定虚拟机的历史 RRD 数据 (用于计算 24h 日流量)"""
        return self._get(f"/nodes/{self.node_name}/qemu/{vmid}/rrddata", params={"timeframe": timeframe})

    def get_usb_devices(self) -> list:
        """获取节点 USB 硬件设备列表"""
        return self._get(f"/nodes/{self.node_name}/hardware/usb")

    def get_vm_config(self, vmid: int) -> dict:
        """获取指定虚拟机的详细硬件配置 (用于匹配 USB 直通)"""
        return self._get(f"/nodes/{self.node_name}/qemu/{vmid}/config")

    def collect_all(self) -> dict:
        """收集所有 PVE API 相关数据"""
        node_status = self.get_node_status()
        rrd_data = self.get_node_rrddata(timeframe="day")
        vms = self.get_vms_status() if isinstance(self.get_vms_status(), list) else []
        lxcs = self.get_lxcs_status() if isinstance(self.get_lxcs_status(), list) else []
        storages = self.get_storage_status() if isinstance(self.get_storage_status(), list) else []
        tasks = self.get_recent_tasks(limit=15)
        raw_usb = self.get_usb_devices()
        
        # 收集每个在线 VM 的 24h/7d/30d RRD 数据及 USB 直通配置
        tr_cfg = self.config.get("traffic", {})
        vm_rrds = {}
        usb_map = {}
        for v in vms:
            vmid = v.get("vmid")
            if vmid:
                if v.get("status") == "running":
                    vm_rrds[vmid] = {}
                    if tr_cfg.get("show_daily", True):
                        vm_rrds[vmid]["day"] = self.get_vm_rrddata(vmid, timeframe="day")
                    if tr_cfg.get("show_weekly", True):
                        vm_rrds[vmid]["week"] = self.get_vm_rrddata(vmid, timeframe="week")
                    if tr_cfg.get("show_monthly", True):
                        vm_rrds[vmid]["month"] = self.get_vm_rrddata(vmid, timeframe="month")
                
                # 检查虚拟机 USB 直通映射
                cfg = self.get_vm_config(vmid)
                if isinstance(cfg, dict):
                    for k, val in cfg.items():
                        if k.startswith("usb") and isinstance(val, str) and "host=" in val:
                            host_id = val.split("host=", 1)[1].split(",", 1)[0].strip().lower()
                            usb_map[host_id] = f"[{vmid}] {v.get('name', '')}"

        # 筛选非 Root Hub 的外接 USB 硬件 (如 WD 外接移动硬盘)
        usb_devices = []
        if isinstance(raw_usb, list):
            for dev in raw_usb:
                if isinstance(dev, dict):
                    vend = str(dev.get("vendid", "")).lower()
                    prod = str(dev.get("prodid", "")).lower()
                    if vend and vend not in ["1d6b", "8087"]:
                        key = f"{vend}:{prod}"
                        mfr = dev.get("manufacturer", "")
                        product = dev.get("product", "USB Storage")
                        speed = dev.get("speed", "")
                        speed_str = "USB 3.0" if speed == "5000" else ("USB 2.0" if speed == "480" else f"{speed}M")
                        passthrough = usb_map.get(key)
                        usb_devices.append({
                            "name": f"{mfr} {product}".strip(),
                            "id": key,
                            "speed": speed_str,
                            "passthrough": passthrough
                        })

        latest_rrd = rrd_data[-1] if rrd_data else {}
        
        return {
            "node_status": node_status,
            "latest_rrd": latest_rrd,
            "rrd_history": rrd_data,
            "vms": vms,
            "lxcs": lxcs,
            "storages": storages,
            "tasks": tasks,
            "vm_rrds": vm_rrds,
            "usb_devices": usb_devices
        }
