import datetime
import jinja2

class BriefingGenerator:
    """状态简报渲染引擎 (支持 Markdown 与 极简苹果风 100% 手机响应式 HTML 邮件)"""

    def __init__(self, node_name: str = "PVE"):
        self.node_name = node_name

    @staticmethod
    def _format_bytes(bytes_val: float) -> str:
        """根据数值自动格式化为 B, KB, MB, GB, TB"""
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
        if not bytes_val:
            return "0.00 GB"
        return f"{bytes_val / (1024 ** 3):.2f} GB"

    @staticmethod
    def _bytes_to_mb_s(bytes_val: float) -> str:
        if not bytes_val:
            return "0.00 MB/s"
        return f"{bytes_val / (1024 ** 2):.2f} MB/s"

    @staticmethod
    def _seconds_to_dhms(seconds: int) -> str:
        if not seconds:
            return "未知"
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        mins = (seconds % 3600) // 60
        return f"{days}天 {hours}小时 {mins}分"

    def build_briefing_data(self, api_data: dict, hw_data: dict, health_data: dict, config: dict = None) -> dict:
        """组装结构化简报数据"""
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

        # 整理存储池空间
        storage_info = []
        for s in raw_storages:
            if isinstance(s, dict) and s.get("active"):
                s_name = s.get("storage", "Unknown")
                s_type = s.get("type", "Unknown")
                s_total = self._bytes_to_gb(s.get("total", 0))
                s_used = self._bytes_to_gb(s.get("used", 0))
                s_avail = self._bytes_to_gb(s.get("avail", 0))
                s_pct = f"{(s.get('used', 0) / s.get('total', 1) * 100):.1f}%" if s.get("total") else "0.0%"
                storage_info.append({
                    "name": s_name,
                    "type": s_type,
                    "total_str": s_total,
                    "used_str": s_used,
                    "avail_str": s_avail,
                    "pct": s_pct
                })

        # 硬件温度
        temps = hw_data.get("temperatures", {})
        cpu_temp = temps.get("cpu_temp", "N/A")
        nvme_temps = temps.get("nvme_temps", {})
        disks_smart = hw_data.get("disks_smart", [])

        # 内存
        mem_total = node_stat.get("memory", {}).get("total", 0)
        mem_used = node_stat.get("memory", {}).get("used", 0)
        mem_percent = (mem_used / mem_total * 100) if mem_total else 0.0
        
        # Swap
        swap_total = node_stat.get("swap", {}).get("total", 0)
        swap_used = node_stat.get("swap", {}).get("used", 0)
        swap_percent = (swap_used / swap_total * 100) if swap_total else 0.0

        # CPU & Uptime
        cpu_usage = node_stat.get("cpu", 0) * 100
        uptime = self._seconds_to_dhms(node_stat.get("uptime", 0))

        # 24h RRD 历史极值与时间戳提取
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

        # VM / LXC 概览与多维度流量极值
        all_guests = vms + lxcs
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
            g_mem = self._bytes_to_gb(g.get("mem", 0))
            g_maxmem = self._bytes_to_gb(g.get("maxmem", 0))
            
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
                "id": g_id, "name": g_name, "mem_str": f"{g_mem} / {g_maxmem}",
                "cpu_max": vm_cpu_max, "cpu_avg": vm_cpu_avg, "cpu_time": vm_cpu_time,
                "mem_max": vm_mem_max, "mem_min": vm_mem_min, "mem_time": vm_mem_time
            })

            net_rx_total = g.get("netin", 0)
            net_tx_total = g.get("netout", 0)
            day_rx, day_tx = _calc_rrd_bytes(day_rrd, 86400.0)
            week_rx, week_tx = _calc_rrd_bytes(v_rrds.get("week", []), 7 * 86400.0)
            month_rx, month_tx = _calc_rrd_bytes(v_rrds.get("month", []), 30 * 86400.0)

            vm_net_stats.append({
                "id": g_id, "name": g_name,
                "day_rx_str": self._format_bytes(day_rx), "day_tx_str": self._format_bytes(day_tx), "day_total_str": self._format_bytes(day_rx + day_tx),
                "week_rx_str": self._format_bytes(week_rx), "week_tx_str": self._format_bytes(week_tx), "week_total_str": self._format_bytes(week_rx + week_tx),
                "month_rx_str": self._format_bytes(month_rx), "month_tx_str": self._format_bytes(month_tx), "month_total_str": self._format_bytes(month_rx + month_tx),
                "total_rx_str": self._format_bytes(net_rx_total), "total_tx_str": self._format_bytes(net_tx_total), "total_str": self._format_bytes(net_rx_total + net_tx_total),
                "sort_key": day_rx + day_tx
            })
        vm_net_stats = sorted(vm_net_stats, key=lambda x: x["sort_key"], reverse=True)

        return {
            "time": now_str, "node_name": self.node_name, "uptime": uptime,
            "cpu_usage": f"{cpu_usage:.1f}%",
            "cpu_temp": f"{cpu_temp}°C" if cpu_temp not in ("N/A", None) else "未检测到",
            "nvme_temps": nvme_temps,
            "mem_used_str": self._bytes_to_gb(mem_used), "mem_total_str": self._bytes_to_gb(mem_total), "mem_percent": f"{mem_percent:.1f}%",
            "swap_used_str": self._bytes_to_gb(swap_used), "swap_total_str": self._bytes_to_gb(swap_total), "swap_percent": f"{swap_percent:.1f}%",
            "net_in_str": self._bytes_to_mb_s(net_in), "net_out_str": self._bytes_to_mb_s(net_out),
            "disk_read_str": self._bytes_to_mb_s(disk_read), "disk_write_str": self._bytes_to_mb_s(disk_write),
            "total_guests": total_guests, "running_count": len(running_guests), "stopped_count": len(stopped_guests),
            "cpu_stats_24h": cpu_stats_24h, "mem_stats_24h": mem_stats_24h, "load_stats_24h": load_stats_24h, "net_stats_24h": net_stats_24h,
            "top_guests": top_guests_info, "vm_net_stats": vm_net_stats,
            "storage_info": storage_info, "disks_smart": disks_smart, "usb_devices": api_data.get("usb_devices", []),
            "show_daily": show_daily, "show_weekly": show_weekly, "show_monthly": show_monthly, "show_total": show_total
        }

    def generate_telegram_html(self, data: dict) -> str:
        """生成适合 Telegram 手机聊天框阅读的紧凑 HTML 简报。"""
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
        """生成 Markdown 格式简报"""
        top_guests_md = ""
        for idx, g in enumerate(data["top_guests"], 1):
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
{storage_md}
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
        top_guests_md = ""
        for idx, g in enumerate(data["top_guests"], 1):
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
{storage_md}
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

    def generate_html(self, data: dict) -> str:
        """生成【 Style 2 极简苹果风】100% 完美支持 iOS/Android 深色模式与手机大字稀疏排版的 HTML 邮件模版"""
        html_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>Proxmox VE 状态简报</title>
<style>
  :root { color-scheme: light dark; supported-color-schemes: light dark; }
  body { background-color: #f5f5f7; color: #1d1d1f; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif; margin: 0; padding: 20px; -webkit-font-smoothing: antialiased; }
  .card { max-width: 720px; margin: 0 auto; background-color: #ffffff; border-radius: 18px; border: 1px solid #e5e5ea; padding: 32px; box-shadow: 0 4px 20px rgba(0,0,0,0.03); box-sizing: border-box; }
  .header { border-bottom: 1px solid #e5e5ea; padding-bottom: 20px; margin-bottom: 26px; }
  .title { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; color: #1d1d1f; margin: 0; }
  .subtitle { font-size: 13px; color: #86868b; margin-top: 6px; }
  .status-row { margin-top: 14px; }
  .status-pill { display: inline-block; padding: 5px 10px; margin: 0 6px 6px 0; border-radius: 999px; background: #f2f2f7; color: #3a3a3c; font-size: 12px; font-weight: 600; }
  .section-title { font-size: 12px; font-weight: 700; color: #0071e3; text-transform: uppercase; letter-spacing: 0.06em; margin: 34px 0 16px 0; border-left: 3px solid #0071e3; padding-left: 10px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-bottom: 24px; }
  .metric-tile { background-color: #fbfbfd; border: 1px solid #e5e5ea; border-radius: 16px; padding: 20px 22px; box-sizing: border-box; }
  .metric-label { font-size: 13px; color: #86868b; font-weight: 500; }
  .metric-value { font-size: 26px; font-weight: 700; color: #1d1d1f; margin-top: 8px; letter-spacing: -0.02em; }
  .metric-sub { font-size: 12px; color: #86868b; margin-top: 6px; line-height: 1.5; }
  .peak-row { padding: 12px 0; border-bottom: 1px solid #f2f2f7; font-size: 13px; }
  .peak-row:last-child { border-bottom: 0; }
  .peak-name { display: inline-block; width: 24%; color: #86868b; }
  .peak-value { display: inline-block; width: 72%; color: #1d1d1f; font-weight: 600; }
  .table-container { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; margin-top: 12px; border-radius: 14px; border: 1px solid #e5e5ea; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 480px; }
  th { text-align: left; padding: 14px 16px; color: #86868b; font-weight: 600; border-bottom: 1px solid #e5e5ea; font-size: 12px; background-color: #fbfbfd; }
  td { padding: 14px 16px; border-bottom: 1px solid #f2f2f7; color: #1d1d1f; line-height: 1.5; }
  .time-badge { font-size: 11px; color: #0071e3; font-weight: 500; }
  .subtext { font-size: 11px; color: #86868b; display: block; margin-top: 3px; }
  .tag-green { color: #34c759; font-weight: 600; }
  .tag-red { color: #ff3b30; font-weight: 600; }
  .footer { margin-top: 40px; font-size: 12px; color: #86868b; text-align: center; border-top: 1px solid #e5e5ea; padding-top: 24px; }
  
  /* 针对 iOS / Android 系统的专属原生深色模式调优 */
  @media (prefers-color-scheme: dark) {
    body { background-color: #000000 !important; color: #f2f2f7 !important; }
    .card { background-color: #1c1c1e !important; border-color: #2c2c2e !important; color: #f2f2f7 !important; }
    .header { border-bottom-color: #2c2c2e !important; }
    .title { color: #ffffff !important; }
    .subtitle { color: #98989d !important; }
    .status-pill { background-color: #2c2c2e !important; color: #f2f2f7 !important; }
    .section-title { color: #64d2ff !important; border-left-color: #64d2ff !important; }
    .metric-tile { background-color: #2c2c2e !important; border-color: #38383a !important; }
    .metric-label { color: #98989d !important; }
    .metric-value { color: #ffffff !important; }
    .metric-sub { color: #98989d !important; }
    .peak-row { border-bottom-color: #2c2c2e !important; }
    .peak-name { color: #98989d !important; }
    .peak-value { color: #f2f2f7 !important; }
    .table-container { border-color: #2c2c2e !important; }
    table { background-color: #1c1c1e !important; }
    th { background-color: #2c2c2e !important; color: #98989d !important; border-bottom-color: #38383a !important; }
    td { border-bottom-color: #2c2c2e !important; color: #f2f2f7 !important; }
    .vm-mobile-card { background-color: #2c2c2e !important; border-color: #38383a !important; color: #f2f2f7 !important; }
    .vm-mobile-title { color: #ffffff !important; border-bottom-color: #38383a !important; }
    .time-badge { color: #64d2ff !important; }
    .subtext { color: #98989d !important; }
    .footer { border-top-color: #2c2c2e !important; color: #98989d !important; }
  }

  .mobile-only { display: none; }
  .desktop-only { display: block; }

  @media only screen and (max-width: 600px) {
    body { padding: 8px !important; }
    .card { padding: 20px 14px !important; border-radius: 16px !important; max-width: 100% !important; overflow: hidden !important; }
    .tile-box { width: 100% !important; margin-right: 0 !important; min-width: 0 !important; margin-bottom: 14px !important; }
    .metric-tile { padding: 18px 20px !important; min-height: 0 !important; }
    .metric-value { font-size: 22px !important; }
    .title { font-size: 20px !important; }
    .desktop-only { display: none !important; }
    .mobile-only { display: block !important; }
    .vm-mobile-card {
      background-color: #fbfbfd;
      border: 1px solid #e5e5ea;
      border-radius: 14px;
      padding: 14px 16px;
      margin-bottom: 14px;
      font-size: 13px;
      line-height: 1.6;
    }
    .vm-mobile-title {
      font-size: 15px;
      font-weight: 700;
      color: #1d1d1f;
      border-bottom: 1px solid #e5e5ea;
      padding-bottom: 8px;
      margin-bottom: 10px;
      display: flex;
      justify-content: space-between;
    }
    .vm-row { display: flex; justify-content: space-between; margin-bottom: 4px; }
    .vm-row-label { color: #86868b; }
    .vm-row-val { font-weight: 500; }
  }
</style>
</head>
<body>
  <div class="card">
    <div class="header">
      <div class="title">Proxmox VE 每日简报 · {{ data.node_name }}</div>
      <div class="subtitle">{{ data.time }} · 已连续运行 {{ data.uptime }}</div>
      <div class="status-row">
        <span class="status-pill">🟢 {{ data.running_count }} 台运行</span>
        <span class="status-pill">🔴 {{ data.stopped_count }} 台停止</span>
        <span class="status-pill">共 {{ data.total_guests }} 台虚拟机 / 容器</span>
      </div>
    </div>

    <div class="section-title">当前状态</div>
    <div style="width: 100%; text-align: left; font-size: 0; margin-bottom: 12px;">
      <div class="tile-box" style="display: inline-block; width: 48%; min-width: 260px; max-width: 100%; vertical-align: top; margin-bottom: 14px; margin-right: 3%; box-sizing: border-box; font-size: 13px;">
        <div class="metric-tile" style="min-height: 125px; box-sizing: border-box;">
          <div class="metric-label">CPU 使用率</div>
          <div class="metric-value">{{ data.cpu_usage }}</div>
          <div class="metric-sub">
            <div>24h 峰值 {{ data.cpu_stats_24h.max }} @{{ data.cpu_stats_24h.peak_time }}</div>
            <div>24h 均值 {{ data.cpu_stats_24h.avg }}</div>
          </div>
        </div>
      </div>
      <div class="tile-box" style="display: inline-block; width: 48%; min-width: 260px; max-width: 100%; vertical-align: top; margin-bottom: 14px; box-sizing: border-box; font-size: 13px;">
        <div class="metric-tile" style="min-height: 125px; box-sizing: border-box;">
          <div class="metric-label">CPU 温度</div>
          <div class="metric-value">{{ data.cpu_temp }}</div>
          <div class="metric-sub">
            <div>当前采集快照</div>
            <div>暂无 24h 温度历史数据</div>
          </div>
        </div>
      </div>
      <div class="tile-box" style="display: inline-block; width: 48%; min-width: 260px; max-width: 100%; vertical-align: top; margin-bottom: 14px; margin-right: 3%; box-sizing: border-box; font-size: 13px;">
        <div class="metric-tile" style="min-height: 125px; box-sizing: border-box;">
          <div class="metric-label">内存占用</div>
          <div class="metric-value">{{ data.mem_percent }}</div>
          <div class="metric-sub">
            <div>已用 {{ data.mem_used_str }} / {{ data.mem_total_str }}</div>
            <div>Swap {{ data.swap_percent }} · {{ data.swap_used_str }} / {{ data.swap_total_str }}</div>
          </div>
        </div>
      </div>
      <div class="tile-box" style="display: inline-block; width: 48%; min-width: 260px; max-width: 100%; vertical-align: top; margin-bottom: 14px; box-sizing: border-box; font-size: 13px;">
        <div class="metric-tile" style="min-height: 125px; box-sizing: border-box;">
          <div class="metric-label">虚拟机 / 容器</div>
          <div class="metric-value">{{ data.running_count }} / {{ data.total_guests }}</div>
          <div class="metric-sub">
            <div>{{ data.running_count }} 台运行 · {{ data.stopped_count }} 台停止</div>
            <div>状态来自当前 PVE 快照</div>
          </div>
        </div>
      </div>
    </div>

    <div class="section-title">24 小时峰值</div>
    <div class="metric-tile">
      <div class="peak-row"><span class="peak-name">CPU</span><span class="peak-value">{{ data.cpu_stats_24h.max }} @{{ data.cpu_stats_24h.peak_time }} · 均值 {{ data.cpu_stats_24h.avg }}</span></div>
      <div class="peak-row"><span class="peak-name">内存</span><span class="peak-value">{{ data.mem_stats_24h.max }} @{{ data.mem_stats_24h.peak_time }} · {{ data.mem_stats_24h.max_pct }}</span></div>
      <div class="peak-row"><span class="peak-name">系统负载</span><span class="peak-value">{{ data.load_stats_24h.max }} @{{ data.load_stats_24h.peak_time }} · 均值 {{ data.load_stats_24h.avg }}</span></div>
      <div class="peak-row"><span class="peak-name">网络带宽</span><span class="peak-value">↓ {{ data.net_stats_24h.max_rx }} · ↑ {{ data.net_stats_24h.max_tx }}</span></div>
    </div>

    <div class="section-title">存储池容量</div>
    <div class="table-container">
      <table>
        <thead>
          <tr><th>名称</th><th>类型</th><th>已用 / 总量</th><th>使用率</th><th>剩余</th></tr>
        </thead>
        <tbody>
          {% for s in data.storage_info %}
          <tr>
            <td><b>{{ s.name }}</b></td>
            <td>{{ s.type }}</td>
            <td>{{ s.used_str }} / {{ s.total_str }}</td>
            <td><b>{{ s.pct }}</b></td>
            <td>{{ s.avail_str }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    {% if data.usb_devices %}
    <div class="section-title">🔌 外接 USB 硬件与直通挂载</div>
    <div class="table-container">
      <table>
        <thead>
          <tr><th>设备名称</th><th>设备 ID</th><th>传输协议</th><th>直通挂载目标</th></tr>
        </thead>
        <tbody>
          {% for u in data.usb_devices %}
          <tr>
            <td><b>🔌 {{ u.name }}</b></td>
            <td><code>{{ u.id }}</code></td>
            <td>{{ u.speed }}</td>
            <td>{% if u.passthrough %}<span class="tag-green">直通 ──► {{ u.passthrough }}</span>{% else %}宿主机本地{% endif %}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% endif %}

    <div class="section-title">🌐 虚拟机网络流量与开机累计</div>
    
    <!-- 桌面端多列表格 -->
    <div class="table-container desktop-only">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>名称</th>
            {% if data.show_daily %}<th>今日 24h 流量</th>{% endif %}
            {% if data.show_weekly %}<th>本周 7d 流量</th>{% endif %}
            {% if data.show_monthly %}<th>本月 30d 流量</th>{% endif %}
            {% if data.show_total %}<th>开机至今累计</th>{% endif %}
          </tr>
        </thead>
        <tbody>
          {% for n in data.vm_net_stats %}
          <tr>
            <td><b>{{ n.id }}</b></td>
            <td>{{ n.name }}</td>
            {% if data.show_daily %}
            <td>⬇️ {{ n.day_rx_str }} · ⬆️ {{ n.day_tx_str }}<span class="subtext">共 {{ n.day_total_str }}</span></td>
            {% endif %}
            {% if data.show_weekly %}
            <td>⬇️ {{ n.week_rx_str }} · ⬆️ {{ n.week_tx_str }}<span class="subtext">共 {{ n.week_total_str }}</span></td>
            {% endif %}
            {% if data.show_monthly %}
            <td>⬇️ {{ n.month_rx_str }} · ⬆️ {{ n.month_tx_str }}<span class="subtext">共 {{ n.month_total_str }}</span></td>
            {% endif %}
            {% if data.show_total %}
            <td>⬇️ {{ n.total_rx_str }} · ⬆️ {{ n.total_tx_str }}<span class="subtext">共 {{ n.total_str }}</span></td>
            {% endif %}
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <!-- 手机端专属卡片列表 (彻底解决多列挤压爆边问题) -->
    <div class="mobile-only">
      {% for n in data.vm_net_stats %}
      <div class="vm-mobile-card">
        <div class="vm-mobile-title">
          <span>🌐 [{{ n.id }}] {{ n.name }}</span>
        </div>
        {% if data.show_daily %}
        <div class="vm-row">
          <span class="vm-row-label">今日 24h 流量:</span>
          <span class="vm-row-val">⬇️ {{ n.day_rx_str }} · ⬆️ {{ n.day_tx_str }} (共 {{ n.day_total_str }})</span>
        </div>
        {% endif %}
        {% if data.show_weekly %}
        <div class="vm-row">
          <span class="vm-row-label">本周 7d 流量:</span>
          <span class="vm-row-val">⬇️ {{ n.week_rx_str }} · ⬆️ {{ n.week_tx_str }}</span>
        </div>
        {% endif %}
        {% if data.show_total %}
        <div class="vm-row">
          <span class="vm-row-label">开机累计流量:</span>
          <span class="vm-row-val">⬇️ {{ n.total_rx_str }} · ⬆️ {{ n.total_tx_str }}</span>
        </div>
        {% endif %}
      </div>
      {% endfor %}
    </div>

    <div class="section-title">📦 虚拟机资源与 24h 性能极值</div>
    
    <!-- 桌面端表格 -->
    <div class="table-container desktop-only">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>名称</th>
            <th>当前内存</th>
            <th>24h CPU 峰值</th>
            <th>24h 内存峰值</th>
          </tr>
        </thead>
        <tbody>
          {% for g in data.top_guests %}
          <tr>
            <td><b>{{ g.id }}</b></td>
            <td>{{ g.name }}</td>
            <td>{{ g.mem_str }}</td>
            <td>{{ g.cpu_max }} <span class="time-badge">(@{{ g.cpu_time }} · 均 {{ g.cpu_avg }})</span></td>
            <td>{{ g.mem_max }} <span class="time-badge">(@{{ g.mem_time }} · 低 {{ g.mem_min }})</span></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <!-- 手机端专属卡片列表 -->
    <div class="mobile-only">
      {% for g in data.top_guests %}
      <div class="vm-mobile-card">
        <div class="vm-mobile-title">
          <span>📦 [{{ g.id }}] {{ g.name }}</span>
        </div>
        <div class="vm-row">
          <span class="vm-row-label">当前内存:</span>
          <span class="vm-row-val">{{ g.mem_str }}</span>
        </div>
        <div class="vm-row">
          <span class="vm-row-label">24h CPU 极值:</span>
          <span class="vm-row-val">🔺 {{ g.cpu_max }} (<span class="time-badge">@{{ g.cpu_time }}</span>) · 均值 {{ g.cpu_avg }}</span>
        </div>
        <div class="vm-row">
          <span class="vm-row-label">24h 内存极值:</span>
          <span class="vm-row-val">🔺 {{ g.mem_max }} (<span class="time-badge">@{{ g.mem_time }}</span>) · 低值 {{ g.mem_min }}</span>
        </div>
      </div>
      {% endfor %}
    </div>

    <div class="footer">pveMonitor 自动化系统简报 · 发送时间 {{ data.time }}</div>
  </div>
</body>
</html>"""
        template = jinja2.Template(html_template)
        return template.render(data=data)
