# 📊 pveMonitor - 开箱即用的 Proxmox VE 自动化状态简报与即时告警系统

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/Python-3.11%2B-green.svg)](https.python.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https.docker.com)
[![Proxmox VE](https://img.shields.io/badge/PVE-7.x%20%7C%208.x-orange.svg)](https://proxmox.com)

`pveMonitor` 是一款专门针对 **Proxmox VE (PVE)** 虚拟化平台设计的轻量级、高颜值、自动化监控简报与异常预警推送系统。采用纯 REST API 架构，无需部署代理或配置复杂 SSH 密钥，即可提供苹果风移动端 HTML 邮件、Telegram Bot 交互命令及多渠道 Webhook 消息推送。

---

## ✨ 核心特性

- 📱 **苹果极简风移动端 HTML 简报**：内置 Style 2 响应式模版，完美适配 iOS/Android 邮件客户端原生深色模式（Dark Mode），提供桌面端 6 列表格与手机端满宽卡片的自动响应式切换。
- 🤖 **Telegram Bot 原生交互式控制**：
  - 发送 `/status` 随时拉取最新实时简报；
  - 发送 `/set_cpu 80` / `/set_nvme 65` 动态调整告警阈值；
  - 发送 `/toggle_alert` 动态暂停 / 恢复后台告警轮询（已与 APScheduler 调度引擎实时联动）；
  - 发送 `/toggle_daily` / `/toggle_weekly` 切换流量维度显示。
- 📊 **24 小时性能极值与发生时刻追踪**：自动记录并标注 CPU 峰值、内存峰值、LoadAvg 及网络带宽最高速率发生的精准时刻（如 `73.5% @19:30`）。
- 🔌 **外接 USB 硬件识别与直通挂载追踪**：自动抓取 PVE 宿主机外接 USB 移动硬盘（如 WD My Passport），并自动关联识别该设备被直通挂载给了哪台虚拟机。
- 🛡️ **纯 PVE REST API 免 SSH 运行**：支持 100% 纯 REST API 抓取物理磁盘 SMART 健康度与 SSD 磨损寿命（Wearout %），零 SSH 风险。
- 📢 **多渠道通知引擎**：支持 SMTP 邮件、Telegram Bot、飞书、钉钉、企业微信、Server酱、Bark 及 PushDeer。

---

## 🚀 快速开始

### 1. 拷贝配置文件模版
```bash
cp config.example.yaml config.yaml
```

### 2. 编辑凭据与监控阈值
编辑 `config.yaml` 填写您的 PVE 节点 IP、凭据以及邮件/Telegram 配置：

```yaml
pve:
  host: "192.168.1.100"
  port: 8006
  node_name: "pve_node_name"
  verify_ssl: false
  auth_type: "token"       # 推荐使用 token 认证，也可设置为 "password"
  user: "root@pam"
  token_id: "pvemonitor"
  token_secret: "YOUR_PVE_API_TOKEN_SECRET"

schedule:
  briefing_cron: "0 8 * * *"    # 每日早 8点 自动发送简报
  alert_interval_seconds: 120   # 每 2 分钟轮询一次异常预警

thresholds:
  temperature:
    cpu_warning: 75
    nvme_warning: 60
  memory:
    usage_percent_warning: 90
    swap_percent_warning: 50
  vms:
    alert_on_stopped: true
    key_vm_ids: [101, 103]
```

### 3. Docker Compose 一键启动
```bash
docker-compose up -d --build
```

---

## 🔒 最小权限与凭据安全 (Least-Privilege Security)

### 1. PVE API 最小权限角色配置 (PVEAuditor)
为了避免使用 `root@pam` 产生安全风险，建议在 PVE 中为 `pveMonitor` 创建一个专属只读 API Token：

1. 在 PVE 管理界面中依次进入 **数据中心 -> 角色 (Roles) -> 添加**：
   - 角色名称：`PVEAuditor`
   - 勾选权限：`Sys.Audit`, `VM.Audit`, `Datastore.Audit`
2. 进入 **数据中心 -> 用户 (Users) -> 添加**：
   - 用户名：`pvemonitor@pve`
   - 角色指派：选择 `PVEAuditor`
3. 进入 **数据中心 -> API Token -> 添加**：
   - 用户：`pvemonitor@pve`
   - Token ID：`monitor`
   - **不要勾选** "Privilege Separation"
4. 将生成的 Token ID 与 Token Secret 填写至 `config.yaml`。

### 2. 秘密与轮换管理
* **禁止将包含明文密码的 `config.yaml` 提交至 Git 仓库**。
* 如需在 CI/CD 或自动化构建中使用，可以通过环境变量覆盖或使用隐藏文件 `.env`：
  ```bash
  export PVE_PASSWORD="YourSecurePassword"
  export TG_BOT_TOKEN="YourTelegramBotToken"
  ```
* 仓库内置 `.dockerignore`，确保 `scratch/` 测试脚本与凭据文件绝不会打包进 Docker 镜像。

---

## 🛠️ Docker 容器安全与参数说明

`docker-compose.yml` 配置示例：

```yaml
version: '3.8'

services:
  pve-monitor:
    build: .
    container_name: pve-monitor
    restart: unless-stopped
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./logs:/app/logs
    healthcheck:
      test: ["CMD-SHELL", "python -c 'import urllib.request; urllib.request.urlopen(\"http://localhost:8006\", timeout=2)' || exit 0"]
      interval: 30s
      timeout: 5s
      retries: 3
```

> ⚠️ **安全特别说明**：
> - `pveMonitor` **不需要** `privileged: true` 特权模式。
> - `pveMonitor` **不需要** `network_mode: host`。容器仅需要通过标准的出站 HTTPS/SMTP 网络访问 PVE API 和通知服务，最大程度隔离容器安全边界。

---

## 🧪 自动化测试与排错

### 运行测试命令
```bash
# 立即触发一次简报测试
python main.py --test-briefing

# 立即触发一次告警推送测试
python main.py --test-alert

# 运行自动化单元测试套件
python -m unittest discover -s tests -p "test_*.py"
```

### 查看实时运行日志
```bash
docker-compose logs -f pve-monitor
```

---

## 📝 开放许可证与版本记录

- **Current Version**: v1.0.0
- **License**: [MIT License](LICENSE)
