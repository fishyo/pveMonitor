import datetime
import jinja2

class BriefingGenerator:
    """Briefing report renderer supporting Markdown, Telegram, and multi-theme responsive HTML emails."""

    def __init__(self, node_name: str = "PVE"):
        self.node_name = node_name

    @staticmethod
    def _format_bytes(bytes_val: float) -> str:
        """Format raw byte counts into human-readable binary units (B to PB)."""
        if not bytes_val or bytes_val <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        idx = 0
        val = float(bytes_val)
        while val >= 1024 and idx < len(units) - 1:
            val /= 1024.0
            idx += 1
        return f"{val:.2f} {units[idx]}"

    @staticmethod
    def _bytes_to_gb(bytes_val: float) -> str:
        """Convert bytes to gigabytes string."""
        if not bytes_val:
            return "0.00 GB"
        return f"{bytes_val / (1024 ** 3):.2f} GB"

    @staticmethod
    def _bytes_to_mb_s(bytes_val: float) -> str:
        """Convert bytes per second rate to MB/s string."""
        if not bytes_val:
            return "0.00 MB/s"
        return f"{bytes_val / (1024 ** 2):.2f} MB/s"

    @staticmethod
    def _seconds_to_dhms(seconds: int) -> str:
        """Convert seconds into day, hour, and minute uptime representation."""
        if not seconds:
            return "未知"
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        mins = (seconds % 3600) // 60
        return f"{days}天 {hours}小时 {mins}分" if days > 0 else f"{hours}小时 {mins}分"

    @staticmethod
    def _get_pct_color(pct: float) -> str:
        """Determine threshold color for gauge and progress bars."""
        if pct >= 85.0:
            return "#ef4444"
        elif pct >= 70.0:
            return "#f59e0b"
        return "#10b981"

    def build_briefing_data(self, api_data: dict, hw_data: dict, health_data: dict, config: dict = None) -> dict:
        """Compile raw metrics into a structured data dictionary for rendering."""
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        config = config or {}
        tr_cfg = config.get("traffic", {})
        show_daily = tr_cfg.get("show_daily", True)
        show_weekly = tr_cfg.get("show_weekly", True)
        show_monthly = tr_cfg.get("show_monthly", True)
        show_total = tr_cfg.get("show_total", True)

        node_stat = api_data.get("node_status", {})
        latest_rrd = api_data.get("latest_rrd", {})
        vms = api_data.get("vms", [])
        lxcs = api_data.get("lxcs", [])
        raw_storages = api_data.get("storages", [])

        # Storage pool capacities and usage breakdown
        storage_info = []
        for s in raw_storages:
            if isinstance(s, dict) and s.get("active"):
                s_name = s.get("storage", "Unknown")
                s_type = s.get("type", "Unknown")
                s_total = self._bytes_to_gb(s.get("total", 0))
                s_used = self._bytes_to_gb(s.get("used", 0))
                s_avail = self._bytes_to_gb(s.get("avail", 0))
                total_val = s.get("total", 0)
                used_val = s.get("used", 0)
                pct_num = round((used_val / total_val * 100), 1) if total_val else 0.0
                storage_info.append({
                    "name": s_name,
                    "type": s_type,
                    "total_str": s_total,
                    "used_str": s_used,
                    "avail_str": s_avail,
                    "pct": f"{pct_num:.1f}%",
                    "pct_num": pct_num,
                    "color": self._get_pct_color(pct_num)
                })

        # Hardware temperatures, SMART health, and UPS
        temps = hw_data.get("temperatures", {})
        cpu_temp = temps.get("cpu_temp", "N/A")
        nvme_temps = temps.get("nvme_temps", {})
        disks_smart = hw_data.get("disks_smart", [])
        formatted_smart = []
        for d in disks_smart:
            wear = d.get("wearout_remaining")
            health_str = d.get("health", "PASSED" if d.get("smart_passed", True) else "FAILED")
            formatted_smart.append({
                "device": d.get("device", "Unknown"),
                "model": d.get("model", "Disk"),
                "smart_passed": d.get("smart_passed", True),
                "health": health_str,
                "wearout": wear if wear is not None else 100,
                "wearout_color": self._get_pct_color(100 - (wear if isinstance(wear, (int, float)) else 100))
            })

        ups_info = hw_data.get("ups", {})
        oom_events = health_data.get("recent_oom_events", [])

        # Host RAM usage
        mem_total = node_stat.get("memory", {}).get("total", 0)
        mem_used = node_stat.get("memory", {}).get("used", 0)
        mem_percent = (mem_used / mem_total * 100) if mem_total else 0.0
        
        # Host swap usage
        swap_total = node_stat.get("swap", {}).get("total", 0)
        swap_used = node_stat.get("swap", {}).get("used", 0)
        swap_percent = (swap_used / swap_total * 100) if swap_total else 0.0

        # CPU usage and system uptime
        cpu_usage = node_stat.get("cpu", 0) * 100
        uptime = self._seconds_to_dhms(node_stat.get("uptime", 0))

        # Host CPU specs & versions
        cpuinfo = node_stat.get("cpuinfo", {})
        cpu_model = cpuinfo.get("model", "")
        cpu_cores = cpuinfo.get("cores", "")
        cpu_threads = cpuinfo.get("cpus", "")
        kernel_ver = node_stat.get("current-kernel", {}).get("release", "") or node_stat.get("kversion", "")
        pve_ver = node_stat.get("pveversion", "")

        # 24-hour RRD historical peak and average analysis
        rrd_history = api_data.get("rrd_history", [])
        
        def _get_peak_info(
            rrd_list: list,
            key: str,
            is_bytes: bool = False,
            is_rate: bool = False,
            percent_ratio: bool = False,
        ) -> tuple:
            valid_items = [r for r in rrd_list if r.get(key) is not None]
            if not valid_items:
                return ("0.0%", "0.0%", "0.0%", "未知") if not is_bytes else ("0.00 GB", "0.00 GB", "0.00 GB", "未知")

            max_item = max(valid_items, key=lambda x: x[key])
            min_item = min(valid_items, key=lambda x: x[key])
            
            t_str = datetime.datetime.fromtimestamp(max_item.get("time", 0)).strftime("%H:%M") if max_item.get("time") else "未知"
            avg_val = sum([r[key] for r in valid_items]) / len(valid_items)

            if is_rate:
                return (self._bytes_to_mb_s(max_item[key]), self._bytes_to_mb_s(min_item[key]), self._bytes_to_mb_s(avg_val), t_str)
            elif is_bytes:
                return (self._bytes_to_gb(max_item[key]), self._bytes_to_gb(min_item[key]), self._bytes_to_gb(avg_val), t_str)
            else:
                scale = 100 if percent_ratio else 1
                return (
                    f"{max_item[key] * scale:.1f}%",
                    f"{min_item[key] * scale:.1f}%",
                    f"{avg_val * scale:.1f}%",
                    t_str,
                )

        cpu_max, cpu_min, cpu_avg, cpu_peak_time = _get_peak_info(
            rrd_history, "cpu", percent_ratio=True
        )
        mem_max, mem_min, mem_avg, mem_peak_time = _get_peak_info(rrd_history, "memused", is_bytes=True)
        memused_history = [
            r["memused"] for r in rrd_history if r.get("memused") is not None
        ]
        net_rx_max, net_rx_min, net_rx_avg, net_rx_peak_time = _get_peak_info(rrd_history, "netin", is_rate=True)
        net_tx_max, net_tx_min, net_tx_avg, net_tx_peak_time = _get_peak_info(rrd_history, "netout", is_rate=True)

        loads_rrd = [r.get("loadavg", 0) for r in rrd_history if r.get("loadavg") is not None]
        load_max_item = max([r for r in rrd_history if r.get("loadavg") is not None], key=lambda x: x["loadavg"]) if loads_rrd else {}
        load_peak_time = datetime.datetime.fromtimestamp(load_max_item.get("time", 0)).strftime("%H:%M") if load_max_item.get("time") else "未知"

        cpu_stats_24h = {"max": cpu_max, "min": cpu_min, "avg": cpu_avg, "peak_time": cpu_peak_time}
        mem_stats_24h = {
            "max": mem_max, "min": mem_min, "avg": mem_avg, "peak_time": mem_peak_time,
            "max_pct": f"{(max(memused_history) / mem_total * 100):.1f}%"
            if (memused_history and mem_total)
            else "0.0%",
        }
        load_stats_24h = {"max": f"{max(loads_rrd):.2f}" if loads_rrd else "0.00", "min": f"{min(loads_rrd):.2f}" if loads_rrd else "0.00", "avg": f"{sum(loads_rrd)/len(loads_rrd):.2f}" if loads_rrd else "0.00", "peak_time": load_peak_time}
        net_stats_24h = {"max_rx": net_rx_max, "max_tx": net_tx_max, "avg_rx": net_rx_avg, "avg_tx": net_tx_avg, "rx_peak_time": net_rx_peak_time}

        net_in = latest_rrd.get("netin", 0)
        net_out = latest_rrd.get("netout", 0)
        disk_read = latest_rrd.get("diskread", 0)
        disk_write = latest_rrd.get("diskwrite", 0)

        # VM vs LXC count breakdown
        valid_vms = [v for v in vms if v.get("template") != 1]
        valid_lxcs = [c for c in lxcs if c.get("template") != 1]
        all_guests = valid_vms + valid_lxcs
        total_guests = len(all_guests)
        running_guests = [g for g in all_guests if g.get("status") == "running"]
        stopped_guests = [g for g in all_guests if g.get("status") != "running"]

        vm_rrds = api_data.get("vm_rrds", {})
        top_guests_info = []
        vm_net_stats = []

        def _calc_rrd_bytes(rrd_list: list, total_seconds: float) -> tuple:
            if not rrd_list or len(rrd_list) < 2:
                return (0.0, 0.0)
            rx_rates = [r.get("netin", 0) for r in rrd_list if r.get("netin") is not None]
            tx_rates = [r.get("netout", 0) for r in rrd_list if r.get("netout") is not None]
            rx_b = (sum(rx_rates) / len(rx_rates)) * total_seconds if rx_rates else 0.0
            tx_b = (sum(tx_rates) / len(tx_rates)) * total_seconds if tx_rates else 0.0
            return (rx_b, tx_b)

        for g in running_guests:
            g_id = g.get("vmid") or g.get("id")
            g_name = g.get("name", "Unknown")
            g_type = "LXC" if (g.get("type") == "lxc" or g in valid_lxcs) else "VM"
            g_mem_val = g.get("mem", 0)
            g_maxmem_val = g.get("maxmem", 1)
            g_mem = self._bytes_to_gb(g_mem_val)
            g_maxmem = self._bytes_to_gb(g_maxmem_val)
            g_mem_pct = round((g_mem_val / g_maxmem_val * 100), 1) if g_maxmem_val else 0.0
            
            v_rrds = vm_rrds.get(g_id, {})
            day_rrd = v_rrds.get("day", [])
            
            vm_cpu_max = "0.0%"
            vm_cpu_avg = "0.0%"
            vm_cpu_time = "未知"
            vm_mem_max = g_mem
            vm_mem_min = g_mem
            vm_mem_time = "未知"

            if day_rrd:
                vm_cpus = [r for r in day_rrd if r.get("cpu") is not None]
                vm_mems = [r for r in day_rrd if r.get("mem") is not None and r.get("mem") > 0]
                if vm_cpus:
                    max_cpu_r = max(vm_cpus, key=lambda x: x["cpu"])
                    vm_cpu_max = f"{max_cpu_r['cpu']*100:.1f}%"
                    vm_cpu_avg = f"{(sum([r['cpu']*100 for r in vm_cpus])/len(vm_cpus)):.1f}%"
                    vm_cpu_time = datetime.datetime.fromtimestamp(max_cpu_r.get("time", 0)).strftime("%H:%M") if max_cpu_r.get("time") else "未知"
                if vm_mems:
                    max_mem_r = max(vm_mems, key=lambda x: x["mem"])
                    min_mem_r = min(vm_mems, key=lambda x: x["mem"])
                    vm_mem_max = self._bytes_to_gb(max_mem_r["mem"])
                    vm_mem_min = self._bytes_to_gb(min_mem_r["mem"])
                    vm_mem_time = datetime.datetime.fromtimestamp(max_mem_r.get("time", 0)).strftime("%H:%M") if max_mem_r.get("time") else "未知"

            top_guests_info.append({
                "id": g_id, "name": g_name, "type": g_type,
                "mem_str": f"{g_mem} / {g_maxmem}", "mem_pct": g_mem_pct,
                "cpu_max": vm_cpu_max, "cpu_avg": vm_cpu_avg, "cpu_time": vm_cpu_time,
                "mem_max": vm_mem_max, "mem_min": vm_mem_min, "mem_time": vm_mem_time
            })

            net_rx_total = g.get("netin", 0)
            net_tx_total = g.get("netout", 0)
            day_rx, day_tx = _calc_rrd_bytes(day_rrd, 86400.0)
            week_rx, week_tx = _calc_rrd_bytes(v_rrds.get("week", []), 7 * 86400.0)
            month_rx, month_tx = _calc_rrd_bytes(v_rrds.get("month", []), 30 * 86400.0)

            vm_net_stats.append({
                "id": g_id, "name": g_name, "type": g_type,
                "day_rx_str": self._format_bytes(day_rx), "day_tx_str": self._format_bytes(day_tx), "day_total_str": self._format_bytes(day_rx + day_tx),
                "week_rx_str": self._format_bytes(week_rx), "week_tx_str": self._format_bytes(week_tx), "week_total_str": self._format_bytes(week_rx + week_tx),
                "month_rx_str": self._format_bytes(month_rx), "month_tx_str": self._format_bytes(month_tx), "month_total_str": self._format_bytes(month_rx + month_tx),
                "total_rx_str": self._format_bytes(net_rx_total), "total_tx_str": self._format_bytes(net_tx_total), "total_str": self._format_bytes(net_rx_total + net_tx_total),
                "sort_key": day_rx + day_tx
            })
        vm_net_stats = sorted(vm_net_stats, key=lambda x: x["sort_key"], reverse=True)

        return {
            "time": now_str, "node_name": self.node_name, "uptime": uptime,
            "cpu_usage": f"{cpu_usage:.1f}%", "cpu_usage_num": round(cpu_usage, 1),
            "cpu_temp": f"{cpu_temp}°C" if cpu_temp not in ("N/A", None) else "未检测到",
            "cpu_temp_val": cpu_temp if isinstance(cpu_temp, (int, float)) else None,
            "nvme_temps": nvme_temps,
            "mem_used_str": self._bytes_to_gb(mem_used), "mem_total_str": self._bytes_to_gb(mem_total),
            "mem_percent": f"{mem_percent:.1f}%", "mem_percent_num": round(mem_percent, 1),
            "swap_used_str": self._bytes_to_gb(swap_used), "swap_total_str": self._bytes_to_gb(swap_total),
            "swap_percent": f"{swap_percent:.1f}%", "swap_percent_num": round(swap_percent, 1),
            "net_in_str": self._bytes_to_mb_s(net_in), "net_out_str": self._bytes_to_mb_s(net_out),
            "disk_read_str": self._bytes_to_mb_s(disk_read), "disk_write_str": self._bytes_to_mb_s(disk_write),
            "total_guests": total_guests, "running_count": len(running_guests), "stopped_count": len(stopped_guests),
            "vm_count": len(valid_vms), "lxc_count": len(valid_lxcs),
            "cpu_model": cpu_model, "cpu_cores": cpu_cores, "cpu_threads": cpu_threads,
            "kernel_ver": kernel_ver, "pve_ver": pve_ver,
            "cpu_stats_24h": cpu_stats_24h, "mem_stats_24h": mem_stats_24h, "load_stats_24h": load_stats_24h, "net_stats_24h": net_stats_24h,
            "top_guests": top_guests_info, "vm_net_stats": vm_net_stats,
            "storage_info": storage_info, "disks_smart": formatted_smart, "usb_devices": api_data.get("usb_devices", []),
            "ups": ups_info, "oom_events": oom_events,
            "show_daily": show_daily, "show_weekly": show_weekly, "show_monthly": show_monthly, "show_total": show_total
        }

    def generate_telegram_html(self, data: dict) -> str:
        """Render a compact HTML briefing optimized for mobile Telegram chat windows."""
        show_d = data.get("show_daily", True)
        show_w = data.get("show_weekly", True)
        show_m = data.get("show_monthly", True)
        show_t = data.get("show_total", True)

        cpu_24h = data.get("cpu_stats_24h", {})
        mem_24h = data.get("mem_stats_24h", {})
        load_24h = data.get("load_stats_24h", {})
        net_24h = data.get("net_stats_24h", {})

        lines = [
            f"📊 <b>PVE 每日简报 · {data['node_name']}</b>",
            f"<code>{data['time']}</code>  ·  在线 {data['uptime']}",
            f"🟢 {data['running_count']} 运行   🔴 {data['stopped_count']} 停止",
            "",
            "<b>宿主机概览</b>",
            f"CPU 使用率  <code>{data['cpu_usage']}</code>",
            f"CPU 温度    <code>{data['cpu_temp']}</code>",
            f"内存        <code>{data['mem_used_str']} / {data['mem_total_str']}</code> ({data['mem_percent']})",
            f"Swap        <code>{data['swap_used_str']} / {data['swap_total_str']}</code> ({data['swap_percent']})",
            "",
            "<b>24 小时峰值</b>",
            f"CPU 使用率  <code>{cpu_24h.get('max')}</code> @{cpu_24h.get('peak_time')} · 均值 {cpu_24h.get('avg')}",
            f"内存使用率  <code>{mem_24h.get('max')}</code> @{mem_24h.get('peak_time')} · 均值 {mem_24h.get('avg')}",
            f"系统负载    <code>{load_24h.get('max')}</code> @{load_24h.get('peak_time')} · 均值 {load_24h.get('avg')}",
            f"网络带宽    ↓ <code>{net_24h.get('max_rx')}</code> · ↑ <code>{net_24h.get('max_tx')}</code>",
        ]

        storage = data.get("storage_info", [])
        if storage:
            lines.extend(["", "<b>存储池</b>"])
            for item in storage:
                lines.append(
                    f"• <b>{item['name']}</b>  {item['pct']}  ·  "
                    f"{item['used_str']} / {item['total_str']}  ·  余 {item['avail_str']}"
                )

        network_by_id = {
            str(item["id"]): item for item in data.get("vm_net_stats", [])
        }
        guests = data.get("top_guests", [])
        if guests:
            lines.extend(["", "<b>虚拟机 / 容器</b>"])
            for guest in guests:
                lines.append(f"• <b>[{guest['id']}] {guest['name']}</b>  ·  内存 {guest['mem_str']}")
                lines.append(
                    f"  CPU 24h {guest['cpu_max']} @{guest['cpu_time']}  ·  均 {guest['cpu_avg']}"
                )
                network = network_by_id.get(str(guest["id"]))
                if network:
                    if show_d:
                        lines.append(
                            f"  今日 ↓ {network['day_rx_str']}  ↑ {network['day_tx_str']}  "
                            f"·  共 {network['day_total_str']}"
                        )
                    if show_w:
                        lines.append(
                            f"  本周 ↓ {network['week_rx_str']}  ↑ {network['week_tx_str']}"
                        )
                    if show_m:
                        lines.append(
                            f"  本月 ↓ {network['month_rx_str']}  ↑ {network['month_tx_str']}"
                        )
                    if show_t:
                        lines.append(
                            f"  累计 ↓ {network['total_rx_str']}  ↑ {network['total_tx_str']}"
                        )

        usb_devices = data.get("usb_devices", [])
        if usb_devices:
            lines.extend(["", "<b>外接设备</b>"])
            for device in usb_devices:
                target = f"  →  {device['passthrough']}" if device.get("passthrough") else ""
                lines.append(
                    f"• {device['name']}  ·  <code>{device['id']}</code>  ·  "
                    f"{device['speed']}{target}"
                )

        lines.extend(["", "<i>pveMonitor · 自动生成</i>"])
        return "\n".join(lines)

    def generate_markdown(self, data: dict) -> str:
        """Render markdown-formatted briefing report without dead code."""
        top_guests_md = ""
        for idx, g in enumerate(data.get("top_guests", []), 1):
            top_guests_md += f"  {idx}. [{g['id']}] {g['name']}\n     • 当前内存: {g['mem_str']}\n     • 24h CPU: 🔺 峰值 {g['cpu_max']} (@{g['cpu_time']}) | ➖ 均值 {g['cpu_avg']}\n     • 24h 内存: 🔺 峰值 {g['mem_max']} (@{g['mem_time']}) | 🔻 低值 {g['mem_min']}\n"
        if not top_guests_md:
            top_guests_md = "  无运行中的虚拟机/容器\n"

        show_d = data.get("show_daily", True)
        show_w = data.get("show_weekly", True)
        show_m = data.get("show_monthly", True)
        show_t = data.get("show_total", True)

        vm_net_md = ""
        for idx, n in enumerate(data.get("vm_net_stats", []), 1):
            vm_net_md += f"  {idx}. [{n['id']}] {n['name']}\n"
            if show_d:
                vm_net_md += f"     • 今日24h: ⬇️ {n['day_rx_str']} | ⬆️ {n['day_tx_str']} (共: {n['day_total_str']})\n"
            if show_w:
                vm_net_md += f"     • 本周7d:  ⬇️ {n['week_rx_str']} | ⬆️ {n['week_tx_str']} (共: {n['week_total_str']})\n"
            if show_m:
                vm_net_md += f"     • 本月30d: ⬇️ {n['month_rx_str']} | ⬆️ {n['month_tx_str']} (共: {n['month_total_str']})\n"
            if show_t:
                vm_net_md += f"     • 开机累计: ⬇️ {n['total_rx_str']} | ⬆️ {n['total_tx_str']} (共: {n['total_str']})\n"

        if not vm_net_md:
            vm_net_md = "  暂未开启任何网络流量维度\n"

        storage_md = ""
        for s in data.get("storage_info", []):
            storage_md += f"• **{s['name']}** ({s['type']}): 已用 {s['used_str']} / 总量 {s['total_str']} (占用 {s['pct']}, 剩余 {s['avail_str']})\n"
        if not storage_md:
            storage_md = "• 无可用存储池数据\n"

        disks_md = ""
        for d in data.get("disks_smart", []):
            disks_md += f"• **{d['device']}** ({d['model']}): SMART {d['health']} | 固态剩余寿命 {d['wearout']}%\n"

        cpu_24h = data.get("cpu_stats_24h", {})
        mem_24h = data.get("mem_stats_24h", {})
        load_24h = data.get("load_stats_24h", {})
        net_24h = data.get("net_stats_24h", {})

        md = f"""📊 **PVE 节点状态简报 ({data['node_name']})**
📅 **时间**: {data['time']} | ⏱️ **在线时间**: {data['uptime']}

----------------------------------------
🌡️ **硬件健康与温度**:
• CPU 负载 / 温度: {data['cpu_usage']} | {data['cpu_temp']}
• 核心存储/固态温度: {data['nvme_temps'] if data['nvme_temps'] else '常温'}

💾 **PVE 存储池容量与占用**:
{storage_md}"""

        if disks_md:
            md += f"""
🛡️ **硬盘健康与耐久评估**:
{disks_md}"""

        md += f"""
📊 **宿主机 24 小时性能极值 (含出现时间)**:
• **CPU 使用率**: 🔺 峰值 {cpu_24h.get('max')} (@{cpu_24h.get('peak_time')}) | 🔻 低值 {cpu_24h.get('min')} | ➖ 平均 {cpu_24h.get('avg')}
• **物理内存**: 🔺 峰值 {mem_24h.get('max')} (@{mem_24h.get('peak_time')} | {mem_24h.get('max_pct')}) | 🔻 低值 {mem_24h.get('min')} | ➖ 平均 {mem_24h.get('avg')}
• **系统 LoadAvg**: 🔺 峰值 {load_24h.get('max')} (@{load_24h.get('peak_time')}) | 🔻 低值 {load_24h.get('min')} | ➖ 平均 {load_24h.get('avg')}
• **最高网络速率**: ⬇️ {net_24h.get('max_rx')} (@{net_24h.get('rx_peak_time')}) | ⬆️ {net_24h.get('max_tx')}

🧠 **宿主机当前内存与 Swap 占用**:
• 物理内存 (RAM): {data['mem_used_str']} / {data['mem_total_str']} ({data['mem_percent']})
• 交换空间 (Swap): {data['swap_used_str']} / {data['swap_total_str']} ({data['swap_percent']})

📈 **宿主机实时网络流量 & 磁盘吞吐**:
• 网络吞吐: ⬇️ 接收 {data['net_in_str']} | ⬆️ 发送 {data['net_out_str']}
• 磁盘 I/O: 📖 读取 {data['disk_read_str']} | ✍️ 写入 {data['disk_write_str']}

🌐 **各虚拟机/容器网络流量多维度统计**:
{vm_net_md}
📦 **各虚拟机/容器 24h 资源占用与极值 (总计 {data['total_guests']} | 🟢 {data['running_count']} 运行 | 🔴 {data['stopped_count']} 停止)**:
{top_guests_md}
----------------------------------------
💡 *监控服务由 pveMonitor 自动生成*"""
        return md

    def generate_html(self, data: dict, theme: str = "newspaper") -> str:
        """Render responsive HTML email supporting multiple design themes."""
        theme_normalized = (theme or "newspaper").lower().strip()
        if theme_normalized in ("newspaper", "vintage"):
            return self._render_newspaper_html(data)
        elif theme_normalized in ("nordic", "warm"):
            return self._render_nordic_html(data)
        elif theme_normalized in ("apple", "clean", "classic"):
            return self._render_apple_html(data)
        else:
            return self._render_newspaper_html(data)

    def _render_newspaper_html(self, data: dict) -> str:
        """Vintage Chronicle / The Proxmox Dispatch editorial newspaper theme."""
        html_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>The Proxmox Dispatch · PVE 每日简报 · {{ data.node_name }}</title>
<style>
  body {
    background-color: #eee7db;
    color: #23201c;
    font-family: "Georgia", "Baskerville", "Times New Roman", "Songti SC", "SimSun", serif;
    margin: 0;
    padding: 24px 10px;
    -webkit-font-smoothing: antialiased;
  }
  .preheader {
    display: none !important;
    visibility: hidden;
    font-size: 1px;
    max-height: 0;
    opacity: 0;
    overflow: hidden;
  }
  .newspaper {
    max-width: 660px;
    margin: 0 auto;
    background: #fbf8f2;
    border: 1px solid #dcd3c3;
    box-shadow: 0 10px 35px rgba(50, 40, 25, 0.12);
    box-sizing: border-box;
    padding: 26px 30px;
  }
  .masthead { text-align: center; padding-bottom: 8px; }
  .motto {
    font-size: 10.5px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #7a6e5e;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-weight: 600;
    margin-bottom: 4px;
  }
  .newspaper-title {
    font-size: 32px;
    font-weight: 900;
    letter-spacing: -0.01em;
    color: #1f1b16;
    margin: 0;
    text-transform: uppercase;
    font-family: "Georgia", "Times New Roman", serif;
    line-height: 1.1;
  }
  .chinese-title {
    font-size: 15px;
    letter-spacing: 0.25em;
    font-weight: 700;
    color: #4a4034;
    margin-top: 4px;
  }
  .issue-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 11px;
    color: #635647;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 6px 0;
    border-top: 1px solid #23201c;
    border-bottom: 1px solid #23201c;
    margin-top: 8px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .headline-box {
    background: #f4ede1;
    border: 1px solid #ded5c4;
    padding: 10px 14px;
    margin: 16px 0 20px 0;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }
  .headline-text { font-size: 13.5px; font-weight: 700; color: #1f1b16; }
  .stamp-tag {
    display: inline-block;
    border: 1.5px solid #9c2c23;
    color: #9c2c23;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 2px 7px;
    border-radius: 3px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .section-headline { text-align: center; position: relative; margin: 24px 0 14px 0; }
  .section-headline span {
    background: #fbf8f2;
    padding: 0 12px;
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #4a3e31;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    position: relative;
    z-index: 1;
  }
  .section-headline:before {
    content: "";
    position: absolute;
    left: 0;
    top: 50%;
    width: 100%;
    height: 1px;
    background: #c5b8a5;
    z-index: 0;
  }
  .grid-2x2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }
  .news-card {
    background: #ffffff;
    border: 1px solid #cfc4b2;
    padding: 12px 14px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-shadow: 2px 2px 0px rgba(0,0,0,0.03);
  }
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .card-label { font-size: 11px; font-weight: 700; color: #7a6e5e; text-transform: uppercase; letter-spacing: 0.05em; }
  .card-stamp { font-size: 10px; font-weight: 700; color: #2e593d; background: #e9f0eb; padding: 1px 5px; border-radius: 2px; }
  .card-num { font-size: 24px; font-weight: 800; color: #1f1b16; margin: 4px 0 6px 0; letter-spacing: -0.02em; line-height: 1; }
  .card-subtext {
    font-size: 11px;
    color: #7a6e5e;
    display: flex;
    justify-content: space-between;
    margin-top: 6px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .meter-bg { width: 100%; height: 5px; background: #e8e0d2; overflow: hidden; border-radius: 2px; }
  .meter-bar { height: 100%; background: #23201c; }
  .news-row-card {
    background: #ffffff;
    border: 1px solid #cfc4b2;
    padding: 12px 14px;
    margin-bottom: 10px;
    box-shadow: 2px 2px 0px rgba(0,0,0,0.03);
  }
  .flex-between { display: flex; justify-content: space-between; align-items: center; }
  .colophon {
    text-align: center;
    padding-top: 18px;
    border-top: 1px solid #cfc4b2;
    margin-top: 24px;
    font-size: 11px;
    color: #7a6e5e;
    line-height: 1.7;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  @media only screen and (max-width: 600px) {
    body { padding: 6px; }
    .newspaper { padding: 18px 14px; }
    .newspaper-title { font-size: 23px; }
    .chinese-title { font-size: 13px; }
    .grid-2x2 { gap: 8px; }
    .card-num { font-size: 20px; }
    .issue-bar { font-size: 10px; flex-wrap: wrap; gap: 4px; }
  }
</style>
</head>
<body>
  <div class="preheader">
    PVE 节点 {{ data.node_name }} 晨间公报 · {{ data.running_count }} 台运行 · CPU {{ data.cpu_usage }} · 内存 {{ data.mem_percent }}
  </div>

  <div class="newspaper">
    <div class="masthead">
      <div class="motto">ALL THE METRICS FIT TO PRINT · 系统运行记录</div>
      <h1 class="newspaper-title">The Proxmox Dispatch</h1>
      <div class="chinese-title">Proxmox VE 每日简报 · {{ data.node_name }}</div>
      <div class="issue-bar">
        <span>节点: {{ data.node_name }}</span>
        <span>{{ data.time.split(' ')[0] }}</span>
        <span>连续在线 {{ data.uptime }}</span>
      </div>
    </div>

    <div class="headline-box">
      <div>
        <span class="stamp-tag">公报快讯</span>
        <span class="headline-text" style="margin-left: 6px;">🟢 {{ data.running_count }} 台运行 · 🔴 {{ data.stopped_count }} 台停止</span>
      </div>
      <span style="font-size: 11.5px; color: #7a6e5e; font-family: -apple-system, sans-serif;">共 {{ data.total_guests }} 台实例</span>
    </div>

    <div class="section-headline"><span>I. 宿主机算力与体温总览</span></div>
    <div class="grid-2x2">
      <div class="news-card">
        <div class="card-header">
          <span class="card-label">CPU 使用率</span>
          <span class="card-stamp">峰值 {{ data.cpu_stats_24h.max }}</span>
        </div>
        <div class="card-num">{{ data.cpu_usage }}</div>
        <div class="meter-bg"><div class="meter-bar" style="width: {{ data.cpu_usage_num }}%;"></div></div>
        <div class="card-subtext">
          <span>24h 均值</span>
          <b>{{ data.cpu_stats_24h.avg }}</b>
        </div>
      </div>

      <div class="news-card">
        <div class="card-header">
          <span class="card-label">核心温度</span>
          <span class="card-stamp" style="color: #2e593d; background: #e3ede6;">{{ data.cpu_temp }}</span>
        </div>
        <div class="card-num" style="color: #2e593d;">{{ data.cpu_temp }}</div>
        <div class="meter-bg"><div class="meter-bar" style="width: {{ data.cpu_temp_val or 45 }}%; background: #2e593d;"></div></div>
        <div class="card-subtext">
          <span>状态快照</span>
          <b>正常</b>
        </div>
      </div>

      <div class="news-card">
        <div class="card-header">
          <span class="card-label">物理内存</span>
          <span class="card-stamp" style="color: #8c5825; background: #fbf0e3;">{{ data.mem_percent }}</span>
        </div>
        <div class="card-num" style="color: #8c5825;">{{ data.mem_used_str }}</div>
        <div class="meter-bg"><div class="meter-bar" style="width: {{ data.mem_percent_num }}%; background: #8c5825;"></div></div>
        <div class="card-subtext">
          <span>总量</span>
          <b>{{ data.mem_total_str }}</b>
        </div>
      </div>

      <div class="news-card">
        <div class="card-header">
          <span class="card-label">交换分区 Swap</span>
          <span class="card-stamp">{{ data.swap_percent }}</span>
        </div>
        <div class="card-num">{{ data.swap_used_str }}</div>
        <div class="meter-bg"><div class="meter-bar" style="width: {{ data.swap_percent_num or 2 }}%;"></div></div>
        <div class="card-subtext">
          <span>总量</span>
          <b>{{ data.swap_total_str }}</b>
        </div>
      </div>
    </div>

    <div class="section-headline"><span>II. 24 小时峰值性能指标</span></div>
    <div class="news-row-card">
      <div class="flex-between" style="font-size: 13px; padding: 4px 0; border-bottom: 1px dashed #ded5c4;">
        <span style="color: #7a6e5e;">CPU 使用率:</span>
        <b>🔺 峰值 {{ data.cpu_stats_24h.max }} @{{ data.cpu_stats_24h.peak_time }} · 均值 {{ data.cpu_stats_24h.avg }}</b>
      </div>
      <div class="flex-between" style="font-size: 13px; padding: 4px 0; border-bottom: 1px dashed #ded5c4;">
        <span style="color: #7a6e5e;">物理内存:</span>
        <b>🔺 峰值 {{ data.mem_stats_24h.max }} @{{ data.mem_stats_24h.peak_time }} · {{ data.mem_stats_24h.max_pct }}</b>
      </div>
      <div class="flex-between" style="font-size: 13px; padding: 4px 0; border-bottom: 1px dashed #ded5c4;">
        <span style="color: #7a6e5e;">系统负载 Load:</span>
        <b>🔺 峰值 {{ data.load_stats_24h.max }} @{{ data.load_stats_24h.peak_time }} · 均值 {{ data.load_stats_24h.avg }}</b>
      </div>
      <div class="flex-between" style="font-size: 13px; padding: 4px 0;">
        <span style="color: #7a6e5e;">网络带宽速率:</span>
        <b>⬇️ {{ data.net_stats_24h.max_rx }} · ⬆️ {{ data.net_stats_24h.max_tx }}</b>
      </div>
    </div>

    <div class="section-headline"><span>III. 存储池配额与固态资产清单</span></div>
    {% for s in data.storage_info %}
    <div class="news-row-card">
      <div class="flex-between">
        <div>
          <b style="font-size: 14.5px; color: #1f1b16;">💾 {{ s.name }}</b>
          <span style="font-size: 11px; color: #7a6e5e; margin-left: 6px; font-family: -apple-system, sans-serif;">[{{ s.type }}]</span>
        </div>
        <b style="font-size: 15px; color: {{ s.color }}; font-family: -apple-system, sans-serif;">{{ s.pct }}</b>
      </div>
      <div class="meter-bg" style="margin: 8px 0;"><div class="meter-bar" style="width: {{ s.pct_num }}%; background: {{ s.color }};"></div></div>
      <div class="flex-between" style="font-size: 12px; color: #7a6e5e; font-family: -apple-system, sans-serif;">
        <span>占用: <b>{{ s.used_str }}</b> / 总额 {{ s.total_str }}</span>
        <span>可用结余: <b style="color: #2e593d;">{{ s.avail_str }}</b></span>
      </div>
    </div>
    {% endfor %}

    {% if data.disks_smart %}
    {% for d in data.disks_smart %}
    <div class="news-row-card">
      <div class="flex-between">
        <div>
          <b style="font-size: 14.5px; color: #1f1b16;">💽 {{ d.device }}</b>
          <span style="font-size: 11.5px; color: #7a6e5e; margin-left: 6px;">{{ d.model }}</span>
        </div>
        <span class="stamp-tag" style="border-color: #2e593d; color: #2e593d;">SMART: {{ d.health }}</span>
      </div>
      <div class="flex-between" style="font-size: 12px; margin-top: 8px; font-family: -apple-system, sans-serif;">
        <span style="color: #7a6e5e;">固态耐久度寿命:</span>
        <b style="color: #2e593d;">{{ d.wearout }}% (良好)</b>
      </div>
      <div class="meter-bg" style="margin-top: 6px;"><div class="meter-bar" style="width: {{ d.wearout }}%; background: #2e593d;"></div></div>
    </div>
    {% endfor %}
    {% endif %}

    {% if data.top_guests %}
    <div class="section-headline"><span>IV. 虚拟机与容器实例名录</span></div>
    {% for g in data.top_guests %}
    <div class="news-row-card">
      <div class="flex-between">
        <div>
          <b style="font-size: 14.5px; color: #1f1b16;">[{{ g.id }}] {{ g.name }}</b>
          <span style="font-size: 10.5px; border: 1px solid #7a6e5e; color: #4a3e31; padding: 1px 5px; margin-left: 6px; font-family: -apple-system, sans-serif;">{{ g.type }}</span>
        </div>
        <span style="color: #2e593d; font-size: 12px; font-weight: 700; font-family: -apple-system, sans-serif;">● 在役运行</span>
      </div>
      <div style="font-size: 12px; color: #7a6e5e; margin: 4px 0 6px 0; font-family: -apple-system, sans-serif;">
        内存: <b>{{ g.mem_str }}</b> ({{ g.mem_pct }}%) · 24h CPU 峰值: {{ g.cpu_max }}
      </div>
    </div>
    {% endfor %}
    {% endif %}

    {% if data.usb_devices %}
    <div class="section-headline"><span>V. 外接硬件设备</span></div>
    {% for u in data.usb_devices %}
    <div class="news-row-card" style="font-size: 12.5px;">
      🔌 <b>{{ u.name }}</b> (<code>{{ u.id }}</code>) · {{ u.speed }} · {% if u.passthrough %}直通 ──► {{ u.passthrough }}{% else %}本地挂载{% endif %}
    </div>
    {% endfor %}
    {% endif %}

    <div class="colophon">
      THE PROXMOX DISPATCH · PRIVATELY PRINTED FOR NODE {{ data.node_name }}<br>
      EDITED & DISPATCHED AUTOMATICALLY BY PVEMONITOR · ALL RIGHTS RESERVED
    </div>
  </div>
</body>
</html>"""
        template = jinja2.Template(html_template, autoescape=True)
        return template.render(data=data)

    def _render_nordic_html(self, data: dict) -> str:
        """Nordic Warm Paper editorial magazine theme."""
        html_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Proxmox VE 每日简报 · {{ data.node_name }}</title>
<style>
  body {
    background-color: #f4efe6;
    color: #2c2824;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Charter", serif;
    margin: 0;
    padding: 22px 10px;
    -webkit-font-smoothing: antialiased;
  }
  .preheader { display: none !important; visibility: hidden; font-size: 1px; max-height: 0; opacity: 0; }
  .container {
    max-width: 660px;
    margin: 0 auto;
    background: #faf8f5;
    border-radius: 14px;
    border: 1px solid #e7dfd5;
    box-shadow: 0 8px 30px rgba(78, 64, 49, 0.08);
    overflow: hidden;
  }
  .header { padding: 26px 28px 18px 28px; background: #fdfbf7; border-bottom: 1px solid #ede5da; }
  .kicker { font-size: 11px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: #8c7355; margin-bottom: 6px; }
  .title { font-size: 22px; font-weight: 700; color: #1f1a16; margin: 0 0 6px 0; }
  .subtitle { font-size: 12.5px; color: #7d7265; line-height: 1.5; }
  .tags-bar { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px; }
  .tag { display: inline-flex; align-items: center; padding: 4px 10px; border-radius: 6px; font-size: 11.5px; font-weight: 600; background: #eee8de; color: #4a3e31; }
  .tag-pine { background: #e3ede6; color: #245237; }
  .content { padding: 22px 28px; }
  .chapter-title { font-size: 11.5px; font-weight: 700; color: #8c7355; text-transform: uppercase; letter-spacing: 0.1em; margin: 24px 0 12px 0; border-bottom: 1px solid #ede5da; padding-bottom: 6px; }
  .chapter-title:first-of-type { margin-top: 0; }
  .grid-2x2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 16px; }
  .paper-card { background: #ffffff; border: 1px solid #e7dfd5; border-radius: 10px; padding: 12px 14px; box-sizing: border-box; display: flex; flex-direction: column; justify-content: space-between; }
  .card-top { display: flex; justify-content: space-between; align-items: center; }
  .kpi-label { font-size: 12px; color: #7d7265; font-weight: 600; }
  .kpi-badge { font-size: 10.5px; font-weight: 600; padding: 2px 6px; border-radius: 4px; background: #f4efe6; color: #635647; }
  .kpi-num { font-size: 22px; font-weight: 700; color: #1f1a16; margin: 6px 0; }
  .kpi-footer { font-size: 11.5px; color: #8a7c6c; margin-top: 6px; display: flex; justify-content: space-between; }
  .track { width: 100%; height: 6px; background: #eee8de; border-radius: 999px; overflow: hidden; }
  .track-bar { height: 100%; border-radius: 999px; }
  .paper-block { background: #ffffff; border: 1px solid #e7dfd5; border-radius: 10px; padding: 13px 15px; margin-bottom: 10px; }
  .flex-between { display: flex; justify-content: space-between; align-items: center; }
  .footer { padding: 20px 28px; background: #f4efe6; border-top: 1px solid #ede5da; font-size: 12px; color: #8c7355; text-align: center; }
  @media only screen and (max-width: 600px) {
    body { padding: 6px; }
    .header, .content { padding: 16px 14px; }
    .grid-2x2 { gap: 8px; }
    .kpi-num { font-size: 19px; }
  }
</style>
</head>
<body>
  <div class="preheader">
    PVE 每日简报 · {{ data.node_name }} · CPU {{ data.cpu_usage }} · 内存 {{ data.mem_percent }} · 运行 {{ data.running_count }}/{{ data.total_guests }}
  </div>

  <div class="container">
    <div class="header">
      <div class="kicker">SYSTEM REPORT · 每日公报</div>
      <h1 class="title">Proxmox VE 每日简报 · {{ data.node_name }}</h1>
      <div class="subtitle">
        生成时间: {{ data.time }} · 连续在线: {{ data.uptime }}
      </div>
      <div class="tags-bar">
        <span class="tag tag-pine">🌿 运行中: {{ data.running_count }} 台</span>
        <span class="tag">停止: {{ data.stopped_count }} 台</span>
        <span class="tag">共计 {{ data.total_guests }} 台实例</span>
      </div>
    </div>

    <div class="content">
      <div class="chapter-title">I. 宿主机性能态势</div>
      <div class="grid-2x2">
        <div class="paper-card">
          <div class="card-top">
            <span class="kpi-label">CPU 使用率</span>
            <span class="kpi-badge">峰值 {{ data.cpu_stats_24h.max }}</span>
          </div>
          <div class="kpi-num" style="color: #4a6b82;">{{ data.cpu_usage }}</div>
          <div class="track"><div class="track-bar" style="width: {{ data.cpu_usage_num }}%; background: #4a6b82;"></div></div>
          <div class="kpi-footer"><span>24h 均值</span><b>{{ data.cpu_stats_24h.avg }}</b></div>
        </div>

        <div class="paper-card">
          <div class="card-top">
            <span class="kpi-label">核心温度</span>
            <span class="kpi-badge" style="background: #e3ede6; color: #245237;">{{ data.cpu_temp }}</span>
          </div>
          <div class="kpi-num" style="color: #245237;">{{ data.cpu_temp }}</div>
          <div class="track"><div class="track-bar" style="width: {{ data.cpu_temp_val or 45 }}%; background: #3b7a57;"></div></div>
          <div class="kpi-footer"><span>状态</span><b>正常</b></div>
        </div>

        <div class="paper-card">
          <div class="card-top">
            <span class="kpi-label">物理内存</span>
            <span class="kpi-badge">{{ data.mem_percent }}</span>
          </div>
          <div class="kpi-num" style="color: #9c5835;">{{ data.mem_used_str }}</div>
          <div class="track"><div class="track-bar" style="width: {{ data.mem_percent_num }}%; background: #9c5835;"></div></div>
          <div class="kpi-footer"><span>总计</span><b>{{ data.mem_total_str }}</b></div>
        </div>

        <div class="paper-card">
          <div class="card-top">
            <span class="kpi-label">交换分区 Swap</span>
            <span class="kpi-badge">{{ data.swap_percent }}</span>
          </div>
          <div class="kpi-num" style="color: #554a3e;">{{ data.swap_used_str }}</div>
          <div class="track"><div class="track-bar" style="width: {{ data.swap_percent_num or 2 }}%; background: #3b7a57;"></div></div>
          <div class="kpi-footer"><span>总计</span><b>{{ data.swap_total_str }}</b></div>
        </div>
      </div>

      <div class="chapter-title">II. 24 小时峰值性能</div>
      <div class="paper-block" style="font-size: 13px; line-height: 1.8;">
        <div>• CPU 使用率: 🔺 峰值 <b>{{ data.cpu_stats_24h.max }}</b> (@{{ data.cpu_stats_24h.peak_time }}) · 均值 {{ data.cpu_stats_24h.avg }}</div>
        <div>• 物理内存: 🔺 峰值 <b>{{ data.mem_stats_24h.max }}</b> (@{{ data.mem_stats_24h.peak_time }}) · {{ data.mem_stats_24h.max_pct }}</div>
        <div>• 系统 Load: 🔺 峰值 <b>{{ data.load_stats_24h.max }}</b> (@{{ data.load_stats_24h.peak_time }}) · 均值 {{ data.load_stats_24h.avg }}</div>
        <div>• 网络吞吐: ⬇️ {{ data.net_stats_24h.max_rx }} · ⬆️ {{ data.net_stats_24h.max_tx }}</div>
      </div>

      <div class="chapter-title">III. 存储池容量与固态损耗</div>
      {% for s in data.storage_info %}
      <div class="paper-block">
        <div class="flex-between">
          <b style="font-size: 14px;">💾 {{ s.name }} ({{ s.type }})</b>
          <b style="color: {{ s.color }};">{{ s.pct }}</b>
        </div>
        <div class="track" style="margin: 8px 0;"><div class="track-bar" style="width: {{ s.pct_num }}%; background: {{ s.color }};"></div></div>
        <div class="flex-between" style="font-size: 12px; color: #7d7265;">
          <span>已占用 {{ s.used_str }} / {{ s.total_str }}</span>
          <span style="color: #245237;">剩余可用 {{ s.avail_str }}</span>
        </div>
      </div>
      {% endfor %}

      {% if data.disks_smart %}
      {% for d in data.disks_smart %}
      <div class="paper-block">
        <div class="flex-between">
          <b style="font-size: 14px;">💽 {{ d.device }} · {{ d.model }}</b>
          <span style="font-size: 11.5px; color: #245237; font-weight: 600;">SMART {{ d.health }}</span>
        </div>
        <div class="flex-between" style="font-size: 12px; color: #7d7265; margin-top: 6px;">
          <span>固态耐久剩余:</span>
          <b style="color: #245237;">{{ d.wearout }}%</b>
        </div>
      </div>
      {% endfor %}
      {% endif %}

      {% if data.top_guests %}
      <div class="chapter-title">IV. 实例名录</div>
      {% for g in data.top_guests %}
      <div class="paper-block">
        <div class="flex-between">
          <b>[{{ g.id }}] {{ g.name }} ({{ g.type }})</b>
          <span style="color: #245237; font-size: 12px;">● 运行中</span>
        </div>
        <div style="font-size: 12px; color: #7d7265; margin-top: 4px;">
          内存: {{ g.mem_str }} · 24h CPU 峰值: {{ g.cpu_max }}
        </div>
      </div>
      {% endfor %}
      {% endif %}

      {% if data.usb_devices %}
      <div class="chapter-title">V. 外接硬件设备</div>
      {% for u in data.usb_devices %}
      <div class="paper-block" style="font-size: 12.5px;">
        🔌 <b>{{ u.name }}</b> (<code>{{ u.id }}</code>) · {{ u.speed }} · {% if u.passthrough %}直通 ──► {{ u.passthrough }}{% else %}本地挂载{% endif %}
      </div>
      {% endfor %}
      {% endif %}
    </div>

    <div class="footer">
      PROXMOX VE MONITOR · NORDIC EDITORIAL · NODE {{ data.node_name }}
    </div>
  </div>
</body>
</html>"""
        template = jinja2.Template(html_template, autoescape=True)
        return template.render(data=data)

    def _render_apple_html(self, data: dict) -> str:
        """Modern clean Apple-inspired light/dark theme."""
        html_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
<title>Proxmox VE 每日简报 · {{ data.node_name }}</title>
<style>
  :root { color-scheme: light dark; }
  body {
    background-color: #f5f5f7;
    color: #1d1d1f;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    margin: 0;
    padding: 20px 10px;
    -webkit-font-smoothing: antialiased;
  }
  .preheader { display: none !important; visibility: hidden; font-size: 1px; max-height: 0; opacity: 0; }
  .card {
    max-width: 680px;
    margin: 0 auto;
    background-color: #ffffff;
    border-radius: 16px;
    border: 1px solid #e5e5ea;
    box-shadow: 0 4px 20px rgba(0,0,0,0.03);
    box-sizing: border-box;
    overflow: hidden;
  }
  .header { padding: 24px 26px 18px 26px; border-bottom: 1px solid #f2f2f7; background: #fafafa; }
  .title { font-size: 21px; font-weight: 700; color: #1d1d1f; margin: 0 0 6px 0; }
  .subtitle { font-size: 12.5px; color: #86868b; }
  .status-row { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px; }
  .status-pill { display: inline-block; padding: 4px 10px; border-radius: 999px; background: #f2f2f7; color: #3a3a3c; font-size: 11.5px; font-weight: 600; }
  .content { padding: 20px 24px; }
  .section-title { font-size: 12px; font-weight: 700; color: #0071e3; text-transform: uppercase; letter-spacing: 0.06em; margin: 24px 0 12px 0; border-left: 3px solid #0071e3; padding-left: 8px; }
  .section-title:first-of-type { margin-top: 0; }
  .metrics-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px; }
  .metric-card { background: #fbfbfd; border: 1px solid #e5e5ea; border-radius: 12px; padding: 12px 14px; box-sizing: border-box; }
  .m-card-top { display: flex; justify-content: space-between; align-items: center; }
  .m-kpi-label { font-size: 12px; color: #86868b; font-weight: 500; }
  .m-kpi-badge { font-size: 10px; font-weight: 600; background: #f2f2f7; color: #3a3a3c; padding: 2px 6px; border-radius: 4px; }
  .m-kpi-val { font-size: 21px; font-weight: 700; color: #1d1d1f; margin: 5px 0; }
  .m-kpi-sub { font-size: 11px; color: #86868b; display: flex; justify-content: space-between; margin-top: 6px; }
  .progress-bg { width: 100%; height: 6px; background-color: #e5e5ea; border-radius: 999px; overflow: hidden; }
  .progress-fill { height: 100%; border-radius: 999px; }
  .block-card { background: #fbfbfd; border: 1px solid #e5e5ea; border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; }
  .flex-between { display: flex; justify-content: space-between; align-items: center; }
  .footer { margin-top: 30px; font-size: 11.5px; color: #86868b; text-align: center; border-top: 1px solid #e5e5ea; padding: 18px; }
  @media (prefers-color-scheme: dark) {
    body { background-color: #0b0f19 !important; color: #f2f2f7 !important; }
    .card { background-color: #1c1c1e !important; border-color: #2c2c2e !important; }
    .header { background: #1c1c1e !important; border-bottom-color: #2c2c2e !important; }
    .title { color: #ffffff !important; }
    .subtitle { color: #98989d !important; }
    .status-pill { background-color: #2c2c2e !important; color: #f2f2f7 !important; }
    .metric-card, .block-card { background-color: #2c2c2e !important; border-color: #38383a !important; }
    .m-kpi-val { color: #ffffff !important; }
    .m-kpi-label, .m-kpi-sub { color: #98989d !important; }
    .m-kpi-badge { background: #38383a !important; color: #f2f2f7 !important; }
    .progress-bg { background-color: #38383a !important; }
    .footer { border-top-color: #2c2c2e !important; color: #98989d !important; }
  }
  @media only screen and (max-width: 600px) {
    body { padding: 6px; }
    .header, .content { padding: 16px 14px; }
    .metrics-grid { gap: 8px; }
    .m-kpi-val { font-size: 19px; }
  }
</style>
</head>
<body>
  <div class="preheader">
    Proxmox VE 每日简报 · {{ data.node_name }} · CPU {{ data.cpu_usage }} · 内存 {{ data.mem_percent }} · 运行 {{ data.running_count }}/{{ data.total_guests }}
  </div>

  <div class="card">
    <div class="header">
      <div class="title">Proxmox VE 每日简报 · {{ data.node_name }}</div>
      <div class="subtitle">{{ data.time }} · 已连续运行 {{ data.uptime }}</div>
      <div class="status-row">
        <span class="status-pill">🟢 {{ data.running_count }} 台运行</span>
        <span class="status-pill">🔴 {{ data.stopped_count }} 台停止</span>
        <span class="status-pill">共 {{ data.total_guests }} 台实例</span>
      </div>
    </div>

    <div class="content">
      <div class="section-title">当前状态</div>
      <div class="metrics-grid">
        <div class="metric-card">
          <div class="m-card-top">
            <span class="m-kpi-label">CPU 使用率</span>
            <span class="m-kpi-badge">峰值 {{ data.cpu_stats_24h.max }}</span>
          </div>
          <div class="m-kpi-val">{{ data.cpu_usage }}</div>
          <div class="progress-bg"><div class="progress-fill" style="width: {{ data.cpu_usage_num }}%; background-color: #0071e3;"></div></div>
          <div class="m-kpi-sub"><span>24h 均值</span><b>{{ data.cpu_stats_24h.avg }}</b></div>
        </div>

        <div class="metric-card">
          <div class="m-card-top">
            <span class="m-kpi-label">CPU 温度</span>
            <span class="m-kpi-badge">快照</span>
          </div>
          <div class="m-kpi-val">{{ data.cpu_temp }}</div>
          <div class="progress-bg"><div class="progress-fill" style="width: {{ data.cpu_temp_val or 45 }}%; background-color: #34c759;"></div></div>
          <div class="m-kpi-sub"><span>状态</span><b>正常</b></div>
        </div>

        <div class="metric-card">
          <div class="m-card-top">
            <span class="m-kpi-label">内存占用</span>
            <span class="m-kpi-badge">{{ data.mem_percent }}</span>
          </div>
          <div class="m-kpi-val">{{ data.mem_used_str }}</div>
          <div class="progress-bg"><div class="progress-fill" style="width: {{ data.mem_percent_num }}%; background-color: #0071e3;"></div></div>
          <div class="m-kpi-sub"><span>总量</span><b>{{ data.mem_total_str }}</b></div>
        </div>

        <div class="metric-card">
          <div class="m-card-top">
            <span class="m-kpi-label">Swap 占用</span>
            <span class="m-kpi-badge">{{ data.swap_percent }}</span>
          </div>
          <div class="m-kpi-val">{{ data.swap_used_str }}</div>
          <div class="progress-bg"><div class="progress-fill" style="width: {{ data.swap_percent_num or 2 }}%; background-color: #34c759;"></div></div>
          <div class="m-kpi-sub"><span>总量</span><b>{{ data.swap_total_str }}</b></div>
        </div>
      </div>

      <div class="section-title">24 小时峰值</div>
      <div class="block-card" style="font-size: 13px; line-height: 1.8;">
        <div class="flex-between"><span>CPU 使用率</span><b>{{ data.cpu_stats_24h.max }} @{{ data.cpu_stats_24h.peak_time }} · 均值 {{ data.cpu_stats_24h.avg }}</b></div>
        <div class="flex-between"><span>内存使用率</span><b>{{ data.mem_stats_24h.max }} @{{ data.mem_stats_24h.peak_time }} · {{ data.mem_stats_24h.max_pct }}</b></div>
        <div class="flex-between"><span>系统负载</span><b>{{ data.load_stats_24h.max }} @{{ data.load_stats_24h.peak_time }} · 均值 {{ data.load_stats_24h.avg }}</b></div>
        <div class="flex-between"><span>网络带宽</span><b>↓ {{ data.net_stats_24h.max_rx }} · ↑ {{ data.net_stats_24h.max_tx }}</b></div>
      </div>

      <div class="section-title">存储池容量</div>
      {% for s in data.storage_info %}
      <div class="block-card">
        <div class="flex-between">
          <b style="font-size: 14px;">{{ s.name }} ({{ s.type }})</b>
          <b style="color: {{ s.color }};">{{ s.pct }}</b>
        </div>
        <div class="progress-bg" style="margin: 8px 0;"><div class="progress-fill" style="width: {{ s.pct_num }}%; background-color: {{ s.color }};"></div></div>
        <div class="flex-between" style="font-size: 12px; color: #86868b;">
          <span>已用 {{ s.used_str }} / {{ s.total_str }}</span>
          <span>余 {{ s.avail_str }}</span>
        </div>
      </div>
      {% endfor %}

      {% if data.disks_smart %}
      <div class="section-title">固态与磁盘健康</div>
      {% for d in data.disks_smart %}
      <div class="block-card">
        <div class="flex-between">
          <b>{{ d.device }} · {{ d.model }}</b>
          <span style="color: #34c759; font-weight: 600; font-size: 12px;">SMART {{ d.health }}</span>
        </div>
        <div class="flex-between" style="font-size: 12px; color: #86868b; margin-top: 6px;">
          <span>固态耐久剩余:</span>
          <b>{{ d.wearout }}%</b>
        </div>
      </div>
      {% endfor %}
      {% endif %}

      {% if data.top_guests %}
      <div class="section-title">虚拟机与容器</div>
      {% for g in data.top_guests %}
      <div class="block-card">
        <div class="flex-between">
          <b>[{{ g.id }}] {{ g.name }} ({{ g.type }})</b>
          <span style="color: #34c759; font-size: 12px;">🟢 运行中</span>
        </div>
        <div style="font-size: 12px; color: #86868b; margin-top: 4px;">
          内存: {{ g.mem_str }} · 24h CPU 峰值: {{ g.cpu_max }}
        </div>
      </div>
      {% endfor %}
      {% endif %}

      {% if data.usb_devices %}
      <div class="section-title">外接硬件设备</div>
      {% for u in data.usb_devices %}
      <div class="block-card" style="font-size: 12.5px;">
        🔌 <b>{{ u.name }}</b> (<code>{{ u.id }}</code>) · {{ u.speed }} · {% if u.passthrough %}直通 ──► {{ u.passthrough }}{% else %}本地挂载{% endif %}
      </div>
      {% endfor %}
      {% endif %}
    </div>

    <div class="footer">pveMonitor 自动化系统简报 · 发送时间 {{ data.time }}</div>
  </div>
</body>
</html>"""
        template = jinja2.Template(html_template, autoescape=True)
        return template.render(data=data)

    def generate_alert_html(self, alert: dict, node_name: str = "PVE") -> str:
        """Render high-priority responsive incident alert card for email dispatch."""
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = alert.get("title", "系统异常告警")
        content = alert.get("content", "")
        key = alert.get("key", "")

        # Determine level and accent color
        is_critical = "temp" in key or "oom" in key
        level_label = "CRITICAL 紧急预警" if is_critical else "WARNING 运行预警"
        banner_bg = "linear-gradient(135deg, #ef4444 0%, #dc2626 100%)" if is_critical else "linear-gradient(135deg, #f59e0b 0%, #d97706 100%)"
        border_color = "#fecaca" if is_critical else "#fde68a"
        box_bg = "#fef2f2" if is_critical else "#fffbeb"

        # Actionable recommendations
        tips = []
        if "cpu_temp" in key:
            tips = [
                "检查宿主机物理机箱与 CPU 散热风扇是否运转正常，有无堵塞或积灰",
                "排查 CPU 硅脂是否干涸，或风道环境温度是否偏高",
                "登录 PVE 控制台运行 <code>htop</code>，排查是否有异常死循环进程占满核心"
            ]
        elif "nvme_temp" in key:
            tips = [
                "检查 NVMe 固态硬盘散热马甲导热垫是否接触紧密",
                "排查是否有大规模持续密集写入作业（如备份、校验等）"
            ]
        elif "memory" in key or "swap" in key:
            tips = [
                "登录 PVE 控制台查看内存排行最高的虚拟机/容器进程",
                "检查是否需要调整特定 VM 的动态内存 (Ballooning) 配额",
                "若 Swap 频繁交换，评估是否需升级物理内存或排查内存泄漏"
            ]
        elif "vm_stopped" in key:
            tips = [
                "登录 PVE Web 管理界面查看该实例的退出日志与任务历史",
                "检查实例所在的底层存储池是否空间耗尽",
                "可尝试通过 Shell 执行 <code>qm start &lt;vmid&gt;</code> 手动拉起实例"
            ]
        elif "oom" in key:
            tips = [
                "查看 <code>journalctl -k</code> 获取被 OOM Killer 杀死的具体进程名",
                "适度增加受影响实例的内存配额，或调低高并发任务并发度"
            ]
        else:
            tips = [
                "请尽快登录 PVE Web 管理平台或通过 SSH 登录节点排查异常状态",
                "监控服务已启动 60 分钟冷却静默期，避免重复轰炸"
            ]

        html_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>⚠️ 【PVE 预警】{{ title }}</title>
<style>
  body {
    background-color: #f3f4f6;
    color: #1f2937;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    margin: 0;
    padding: 24px 12px;
  }
  .preheader { display: none !important; visibility: hidden; font-size: 1px; max-height: 0; opacity: 0; }
  .alert-container {
    max-width: 620px;
    margin: 0 auto;
    background-color: #ffffff;
    border-radius: 16px;
    border: 1px solid {{ border_color }};
    box-shadow: 0 4px 25px rgba(220, 38, 38, 0.08);
    overflow: hidden;
  }
  .alert-banner {
    background: {{ banner_bg }};
    padding: 24px 28px;
    color: #ffffff;
  }
  .alert-badge {
    display: inline-block;
    background: rgba(255, 255, 255, 0.22);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    padding: 3px 10px;
    border-radius: 999px;
    text-transform: uppercase;
    margin-bottom: 8px;
  }
  .alert-title { font-size: 22px; font-weight: 700; margin: 0 0 6px 0; }
  .alert-desc { font-size: 13px; color: rgba(255, 255, 255, 0.9); margin: 0; line-height: 1.5; }
  .alert-body { padding: 24px 28px; }
  .incident-box {
    background: {{ box_bg }};
    border: 1px solid {{ border_color }};
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 20px;
  }
  .data-grid { width: 100%; border-collapse: collapse; }
  .data-grid td { padding: 8px 4px; font-size: 13px; vertical-align: middle; }
  .label-col { color: #6b7280; width: 32%; }
  .val-col { color: #111827; font-weight: 600; }
  .guide-title { font-size: 13px; font-weight: 700; color: #374151; margin: 18px 0 10px 0; text-transform: uppercase; letter-spacing: 0.04em; }
  .guide-list { margin: 0; padding-left: 18px; font-size: 13px; color: #4b5563; line-height: 1.7; }
  .guide-list code { background: #f3f4f6; padding: 2px 6px; border-radius: 4px; color: #1f2937; font-size: 12px; }
  .alert-footer { padding: 16px 28px; background-color: #fafafa; border-top: 1px solid #f3f4f6; font-size: 12px; color: #9ca3af; text-align: center; }
  @media only screen and (max-width: 600px) {
    body { padding: 6px; }
    .alert-banner, .alert-body { padding: 18px 16px; }
    .alert-title { font-size: 19px; }
  }
</style>
</head>
<body>
  <div class="preheader">【{{ level_label }}】{{ title }} - 节点 {{ node_name }}</div>
  <div class="alert-container">
    <div class="alert-banner">
      <span class="alert-badge">{{ level_label }}</span>
      <h1 class="alert-title">{{ title }}</h1>
      <p class="alert-desc">PVE 监控服务检测到异常指标超限，请核实系统状态并排查原因。</p>
    </div>

    <div class="alert-body">
      <div class="incident-box">
        <table class="data-grid">
          <tr>
            <td class="label-col">监控节点</td>
            <td class="val-col"><b>{{ node_name }}</b></td>
          </tr>
          <tr>
            <td class="label-col">预警详情</td>
            <td class="val-col">{{ content }}</td>
          </tr>
          <tr>
            <td class="label-col">检测时间</td>
            <td class="val-col">{{ now_str }}</td>
          </tr>
        </table>
      </div>

      <div class="guide-title">🛠️ 建议排查与恢复指引</div>
      <ol class="guide-list">
        {% for tip in tips %}
        <li>{{ tip | safe }}</li>
        {% endfor %}
      </ol>
    </div>

    <div class="alert-footer">
      pveMonitor 告警引擎自动推送 · 同一规则已进入冷却防刷周期
    </div>
  </div>
</body>
</html>"""
        template = jinja2.Template(html_template, autoescape=True)
        return template.render(
            title=title, content=content, node_name=node_name, now_str=now_str,
            level_label=level_label, banner_bg=banner_bg, border_color=border_color,
            box_bg=box_bg, tips=tips
        )
