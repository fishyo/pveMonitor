# pveMonitor

Proxmox VE 状态监控、每日简报与异常预警服务。通过 PVE REST API 采集节点、虚拟机、容器、磁盘 SMART 及外接硬件状态，支持邮件、Telegram 与 Webhook 多渠道推送。

## 特性

- **免特权采集**：基于 PVE REST API，无需宿主机特权模式或挂载系统目录。
- **定时简报**：支持 Cron 定时生成节点与虚拟机状态简报（HTML 邮件、Markdown、Telegram 消息）。
- **实时告警**：支持 CPU/NVMe 温度、内存、Swap 占用率及关键实例停机告警，内置冷却防刷屏机制。
- **Telegram 交互**：支持通过 Telegram Bot 实时查询状态、硬件温度，并动态调整阈值与监控范围。
- **多渠道分发**：支持 SMTP 邮件、Telegram Bot 及主流 Webhook（飞书、钉钉、企业微信、Bark 等）。

## 快速部署

### 1. 准备配置

下载配置模板并保存为 `config.yaml`：

```bash
curl -fsSL https://raw.githubusercontent.com/fishyo/pveMonitor/master/config.example.yaml -o config.yaml
```

根据实际环境修改 `config.yaml` 中的 PVE 连接信息及通知渠道。

### 2. 使用 Docker Compose 运行

创建 `docker-compose.yml`：

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

启动服务：

```bash
docker compose up -d
```

## 配置参考

`config.yaml` 核心配置结构如下：

```yaml
pve:
  host: "192.168.1.100"
  port: 8006
  node_name: "pve"
  verify_ssl: false
  auth_type: "token"          # 可选: token 或 password
  user: "root@pam"
  token_id: "pvemonitor"
  token_secret: "YOUR_TOKEN_SECRET"

schedule:
  briefing_cron: "0 8 * * *"   # 每天 08:00 发送简报
  alert_interval_seconds: 120  # 告警轮询间隔（秒），设为 0 暂停

thresholds:
  temperature:
    cpu_warning: 75
    nvme_warning: 60
  memory:
    usage_percent_warning: 90
    swap_percent_warning: 50
  vms:
    alert_on_stopped: true
    key_vm_ids: [100, 101]     # 重点监控实例 ID；留空则监控全部非模板实例

notifiers:
  email:
    enabled: false
    smtp_host: "smtp.example.com"
    smtp_port: 465
    use_ssl: true
    username: "user@example.com"
    password: "YOUR_PASSWORD"
    sender: "pveMonitor <user@example.com>"
    receivers:
      - "user@example.com"

  telegram:
    enabled: true
    briefing_enabled: true
    bot_token: "YOUR_TELEGRAM_BOT_TOKEN"
    chat_id: "YOUR_TELEGRAM_CHAT_ID"

  webhook:
    enabled: false
    type: "feishu"             # 支持: feishu, dingtalk, wechat, serverchan, bark
    url: ""
```

支持通过环境变量覆盖敏感凭据：`PVE_HOST`、`PVE_PASSWORD`、`TG_BOT_TOKEN`、`TG_CHAT_ID`、`SMTP_PASSWORD`。

## Telegram Bot 指令

| 指令 | 说明 |
| :--- | :--- |
| `/manage` 或 `/menu` | 打开管理控制面板（阈值、实例监控、通知渠道开关） |
| `/status` | 实时拉取并回复当前节点与虚拟机运行状态简报 |
| `/temp` | 查看实时硬件温度（CPU Package/核心、NVMe/磁盘） |
| `/key_vms` | 实例监控点选菜单 |
| `/set_cpu <温度>` | 设置 CPU 告警阈值（例：`/set_cpu 75`） |
| `/set_nvme <温度>` | 设置 NVMe 告警阈值（例：`/set_nvme 60`） |
| `/set_mem <百分比>` | 设置内存告警阈值（例：`/set_mem 90`） |
| `/set_key_vms <IDs>` | 批量设置监控实例（例：`/set_key_vms 100,101`，清空填 `clear`） |
| `/add_key_vm <ID>` | 添加单个实例到重点监控列表 |
| `/del_key_vm <ID>` | 从重点监控列表中移除指定实例 |
| `/toggle_alert` | 暂停或恢复后台告警轮询 |
| `/toggle_briefing` | 开启或关闭 Telegram 定时简报推送 |
| `/cancel` | 清空 Telegram 消息队列积压并重置限频计数器 |

## 常用测试命令

```bash
# 触发一次测试简报发送
docker compose exec pve-monitor python main.py --test-briefing

# 触发一次测试告警发送
docker compose exec pve-monitor python main.py --test-alert

# 执行容器健康检查
docker compose exec pve-monitor python healthcheck.py

# 执行单元测试套件
python -m unittest discover -s tests -p "test_*.py"
```

## 许可证

[MIT License](LICENSE)
