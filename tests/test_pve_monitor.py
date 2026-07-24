import unittest
from unittest.mock import MagicMock, patch
import requests
from engine.briefing import BriefingGenerator
from engine.alerter import AlertEngine
from notifiers.manager import NotificationManager
from notifiers.webhook_notifier import WebhookNotifier
from collectors.pve_api import PVECollector
from collectors.hardware import HardwareCollector
from collectors.system_health import SystemHealthCollector

class TestPVEMonitor(unittest.TestCase):

    def setUp(self):
        self.config = {
            "pve": {"host": "127.0.0.1", "port": 8006, "node_name": "test_node", "verify_ssl": False, "auth_type": "password", "user": "root@pam", "password": "wrong_password"},
            "thresholds": {
                "temperature": {"cpu_warning": 75, "nvme_warning": 60},
                "memory": {"usage_percent_warning": 90, "swap_percent_warning": 50},
                "vms": {"alert_on_stopped": True, "key_vm_ids": [101]}
            },
            "alert_cooldown_minutes": 60,
            "notifiers": {
                "email": {"enabled": False},
                "telegram": {"enabled": False},
                "webhook": {"enabled": False, "type": "bark", "url": "https://api.day.app/test/msg"}
            }
        }
        self.briefing_gen = BriefingGenerator(node_name="test_node")

    def test_briefing_generators(self):
        sample_data = {
            "node_name": "test_node",
            "time": "2026-07-24 20:00:00",
            "uptime": "100天",
            "cpu_usage": "15.0%",
            "cpu_temp": "45.0°C",
            "nvme_temps": {"nvme0": 40.0},
            "mem_used_str": "8.0 GB",
            "mem_total_str": "16.0 GB",
            "mem_percent": "50.0%",
            "swap_used_str": "0.0 GB",
            "swap_total_str": "4.0 GB",
            "swap_percent": "0.0%",
            "net_in_str": "10 MB/s",
            "net_out_str": "5 MB/s",
            "disk_read_str": "1 MB/s",
            "disk_write_str": "2 MB/s",
            "total_guests": 2,
            "running_count": 2,
            "stopped_count": 0,
            "cpu_stats_24h": {"max": "35%", "peak_time": "12:00", "min": "5%", "avg": "10%"},
            "mem_stats_24h": {"max": "60%", "peak_time": "14:00", "max_pct": "60%", "min": "40%", "avg": "50%"},
            "load_stats_24h": {"max": "2.5", "peak_time": "15:00", "min": "0.2", "avg": "0.8"},
            "net_stats_24h": {"max_rx": "50 MB/s", "rx_peak_time": "18:00", "max_tx": "30 MB/s"},
            "top_guests": [
                {"id": 101, "name": "omv", "mem_str": "6.0 GB", "cpu_max": "20%", "cpu_time": "10:00", "cpu_avg": "5%", "mem_max": "6.0 GB", "mem_time": "10:00", "mem_min": "4.0 GB"}
            ],
            "vm_net_stats": [],
            "storage_info": [{"name": "local", "type": "dir", "used_str": "10 GB", "total_str": "100 GB", "pct": "10%", "avail_str": "90 GB"}],
            "disks_smart": [],
            "usb_devices": [{"name": "Western Digital My Passport", "id": "1058:0830", "speed": "USB 3.0", "passthrough": "[101] omv"}],
            "show_daily": True, "show_weekly": True, "show_monthly": True, "show_total": True
        }

        md = self.briefing_gen.generate_markdown(sample_data)
        self.assertIn("PVE 节点状态简报 (test_node)", md)
        self.assertIn("45.0°C", md)

        html = self.briefing_gen.generate_html(sample_data)
        self.assertIn("Proxmox VE 运行状态快照", html)
        self.assertIn("Western Digital My Passport", html)

        tg_html = self.briefing_gen.generate_telegram_html(sample_data)
        self.assertIn("<b>🌡️ 硬件健康</b>", tg_html)
        self.assertIn("Western Digital My Passport", tg_html)

    def test_alert_engine_thresholds(self):
        engine = AlertEngine(self.config)
        api_data = {
            "node_status": {
                "memory": {"used": 15 * (1024**3), "total": 16 * (1024**3)},
                "swap": {"used": 3 * (1024**3), "total": 4 * (1024**3)}
            },
            "vms": [{"vmid": 101, "name": "omv", "status": "stopped"}],
            "lxcs": []
        }
        hw_data = {"temperatures": {"cpu_temp": 80.0, "nvme_temps": {"nvme0": 65.0}}}
        health_data = {"recent_oom_events": []}

        alerts = engine.check_alerts(api_data, hw_data, health_data)
        alert_keys = [a["key"] for a in alerts]

        self.assertIn("cpu_temp_high", alert_keys)
        self.assertIn("nvme_temp_high_nvme0", alert_keys)
        self.assertIn("memory_high", alert_keys)
        self.assertIn("swap_high", alert_keys)
        self.assertIn("vm_stopped_101", alert_keys)

    @patch("requests.post")
    def test_pve_api_auth_failure_recovery(self, mock_post):
        mock_post.side_effect = requests.exceptions.RequestException("401 Unauthorized")
        collector = PVECollector(self.config)
        self.assertEqual(collector.cookies, {})
        # Verify fallback response is empty dict without crashing
        data = collector.get_node_status()
        self.assertEqual(data, {})

    @patch("requests.get")
    def test_pve_api_pve7_pve8_compatibility(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"devpath": "/dev/sda", "model": "KINGSTON", "health": "PASSED", "wearout": 99}
            ]
        }
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        collector = PVECollector(self.config)
        disks = collector.get_disks_list()
        self.assertEqual(len(disks), 1)
        self.assertEqual(disks[0]["health"], "PASSED")

        hw_collector = HardwareCollector(self.config)
        smart_info = hw_collector.collect_from_pve_collector(collector)
        self.assertEqual(len(smart_info), 1)
        self.assertTrue(smart_info[0]["smart_passed"])

    def test_notification_manager_reset(self):
        nm = NotificationManager(self.config)
        initial_count = len(nm.notifiers)
        nm._init_notifiers()
        self.assertEqual(len(nm.notifiers), initial_count)

    def test_webhook_notifier(self):
        wn = WebhookNotifier(self.config)
        self.assertEqual(wn.webhook_type, "bark")

if __name__ == "__main__":
    unittest.main()
