import logging
import threading
import urllib3
import requests

# Suppress insecure HTTPS connection warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("pveMonitor.collectors.pve_api")

class PVECollector:
    """Proxmox VE REST API metrics collector."""
    
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
        self._reauth_lock = threading.Lock()
        
        self._setup_auth()

    def _setup_auth(self):
        """Configure API token or session ticket credentials."""
        if self.auth_type == "token":
            user = self.config.get("user", "")
            token_id = self.config.get("token_id", "")
            token_secret = self.config.get("token_secret", "")
            auth_header = f"PVEAPIToken={user}!{token_id}={token_secret}"
            self.headers["Authorization"] = auth_header
            logger.info("已配置 PVE API Token 认证")
        else:
            # Password ticket authentication mode
            self._login_with_password()

    def _login_with_password(self):
        """Authenticate with username and password to retrieve ticket and CSRF token."""
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
        """Execute a GET request with automatic token re-authentication on 401."""
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
            if resp.status_code == 401 and self.auth_type == "password":
                logger.info("PVE 登录票据已过期，正在自动重新认证")
                with self._reauth_lock:
                    self._login_with_password()
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
        """Fetch node aggregate status (CPU, memory, swap, uptime, KSM)."""
        return self._get(f"/nodes/{self.node_name}/status")

    def get_node_rrddata(self, timeframe: str = "day") -> list:
        """Fetch node historical RRD data (network IO, disk IO, CPU, load)."""
        return self._get(f"/nodes/{self.node_name}/rrddata", params={"timeframe": timeframe})

    def get_vms_status(self) -> list:
        """Fetch QEMU VM instances and status list."""
        return self._get(f"/nodes/{self.node_name}/qemu")

    def get_lxcs_status(self) -> list:
        """Fetch LXC container instances and status list."""
        return self._get(f"/nodes/{self.node_name}/lxc")

    def get_storage_status(self) -> list:
        """Fetch storage pools status and capacity metrics."""
        return self._get(f"/nodes/{self.node_name}/storage")

    def get_recent_tasks(self, limit: int = 20) -> list:
        """Fetch recent node tasks (e.g. backup vzdump results)."""
        return self._get(f"/nodes/{self.node_name}/tasks", params={"limit": limit})

    def get_disks_list(self) -> list:
        """Fetch physical disk devices and SMART health status via API."""
        return self._get(f"/nodes/{self.node_name}/disks/list")

    def get_vm_rrddata(self, vmid: int, timeframe: str = "day") -> list:
        """Fetch historical RRD metrics for a specific VM."""
        return self._get(f"/nodes/{self.node_name}/qemu/{vmid}/rrddata", params={"timeframe": timeframe})

    def get_usb_devices(self) -> list:
        """Fetch host USB hardware devices list."""
        return self._get(f"/nodes/{self.node_name}/hardware/usb")

    def get_vm_config(self, vmid: int) -> dict:
        """Fetch hardware configuration of a VM to map USB passthrough devices."""
        return self._get(f"/nodes/{self.node_name}/qemu/{vmid}/config")

    def collect_all(self) -> dict:
        """Collect and aggregate all PVE API metrics."""
        node_status = self.get_node_status()
        rrd_data = self.get_node_rrddata(timeframe="day")
        # Collect cluster resources
        raw_vms = self.get_vms_status()
        vms = raw_vms if isinstance(raw_vms, list) else []
        raw_lxcs = self.get_lxcs_status()
        lxcs = raw_lxcs if isinstance(raw_lxcs, list) else []
        raw_storages = self.get_storage_status()
        storages = raw_storages if isinstance(raw_storages, list) else []
        tasks = self.get_recent_tasks(limit=15)
        raw_usb = self.get_usb_devices()
        
        # Collect per-VM RRD traffic metrics and USB passthrough mappings
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
                
                # Check USB passthrough mapping in VM configuration
                cfg = self.get_vm_config(vmid)
                if isinstance(cfg, dict):
                    for k, val in cfg.items():
                        if k.startswith("usb") and isinstance(val, str) and "host=" in val:
                            host_id = val.split("host=", 1)[1].split(",", 1)[0].strip().lower()
                            usb_map[host_id] = f"[{vmid}] {v.get('name', '')}"

        # Filter external USB hardware devices (excluding virtual root hubs)
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
