# pveMonitor

Proxmox VE 状态每日简报与即时异常预警服务。通过 PVE REST API 采集节点、虚拟机、容器、磁盘 SMART 及外接 USB 硬件状态，支持邮件、Telegram Bot 及 Webhook 推送。

---

## ⚡ 快速部署

### 1. 准备配置文件
获取配置模版并按需修改：
```bash
wget https://raw.githubusercontent.com/fishyo/pveMonitor/master/config.example.yaml -O config.yaml
```

### 2. 使用 Docker Compose 运行 (推荐)
无需本地构建，直接拉取 GitHub 容器镜像 (GHCR)：

```yaml
version: '3.8'

services:
  pve-monitor:
    image: ghcr.io/fishyo/pvemonitor:latest
    container_name: pve-monitor
    restart: unless-stopped
    volumes:
      - ./config.yaml:/app/config.yaml
    environment:
      - TZ=Asia/Shanghai
    healthcheck:
      test: ["CMD", "python", "healthcheck.py"]
      interval: 30s
      timeout: 5s
      retries: 3
```

启动容器：
```bash
docker compose up -d
```

---

## ⚙️ 核心配置说明 (`config.yaml`)

```yaml
pve:
  host: "192.168.1.100"
  port: 8006
  node_name: "pve"
  verify_ssl: false
  auth_type: "password"      # 选填 password 或 token
  user: "root@pam"
  password: "YOUR_PVE_PASSWORD"

schedule:
  briefing_cron: "0 8 * * *"   # 每日 08:00 发送简报
  alert_interval_seconds: 120  # 每 2 分钟轮询告警 (设为 0 可暂停轮询)

thresholds:
  temperature:
    cpu_warning: 75
    nvme_warning: 60
  memory:
    usage_percent_warning: 90
    swap_percent_warning: 50
  vms:
    alert_on_stopped: true
    key_vm_ids: [100, 101]

notifiers:
  email:
    enabled: true
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    use_ssl: false
    username: "your_email@gmail.com"
    password: "YOUR_SMTP_PASSWORD"
    sender: "PVE 监控服务 <your_email@gmail.com>"
    receivers:
      - "your_email@gmail.com"

  telegram:
    enabled: true
    bot_token: "YOUR_TELEGRAM_BOT_TOKEN"
    chat_id: "YOUR_TELEGRAM_CHAT_ID"
```

> **环境变量覆盖支持**：可在容器中配置环境变量 `PVE_HOST`、`PVE_PASSWORD`、`TG_BOT_TOKEN`、`TG_CHAT_ID` 及 `SMTP_PASSWORD`，自动覆盖配置文件中的对应字段。

---

## 🛡️ PVE API 最小权限配置

如需避免使用 `root` 账户，可在 PVE 管理界面中创建专属只读 API Token：

1. **创建角色**：数据中心 -> 角色 -> 添加角色 `PVEAuditor`（权限：`Sys.Audit`, `VM.Audit`, `Datastore.Audit`）。
2. **创建用户与 Token**：数据中心 -> 用户 -> 添加 `pvemonitor@pve` 指派 `PVEAuditor` 角色；进入 API Token 添加 Token 并填入 `config.yaml`。

---

## 🤖 Telegram Bot 交互指令

向 Telegram Bot 发送以下指令即可实现实时交互：
- `/status` - 立即拉取并返回最新简报
- `/set_cpu <温度>` - 动态修改 CPU 告警阈值
- `/set_nvme <温度>` - 动态修改 NVMe 固态告警阈值
- `/toggle_alert` - 动态暂停 / 恢复后台告警轮询
- `/toggle_daily` - 开关简报 24h 流量统计

---

## 🧪 常用测试命令

```bash
# 立即触发一次简报推送测试
docker compose exec pve-monitor python main.py --test-briefing

# 立即触发一次告警推送测试
docker compose exec pve-monitor python main.py --test-alert

# 运行容器内部健康检查
docker compose exec pve-monitor python healthcheck.py
```

---

## 📄 开源协议

[MIT License](LICENSE)
