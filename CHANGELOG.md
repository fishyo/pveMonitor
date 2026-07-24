# 📋 CHANGELOG - pveMonitor 更新日志与发布说明

本文档记录 `pveMonitor` 的版本更新历史、兼容性说明、升级/回滚指南及已知问题。

---

## 🚀 [v1.0.0] - 2026-07-24 (正式生产发布版)

### ✨ 新增功能 (Features)
- 📱 ** Style 2 苹果风响应式 HTML 简报**：支持桌面端 6 列表格与手机端满宽卡片的自动切换，原生适配 iOS/Android 邮件深色模式 (Dark Mode)。
- 🤖 **Telegram Bot 原生交互监听**：支持 `/status` 实时触发简报，支持 `/toggle_alert` 动态暂停/恢复后台告警轮询（与 APScheduler 调度引擎实时同步）。
- 📊 **24 小时性能极值与发生时刻**：记录并标注 CPU 峰值、内存峰值、LoadAvg 及网络带宽最高速率发生的精准时刻（如 `73.5% @19:30`）。
- 🔌 **外接 USB 硬件识别与直通追踪**：自动识别 PVE 宿主机外接 USB 移动硬盘（如 WD My Passport），并自动匹配关联直通目标虚拟机。
- 🛡️ **纯 PVE REST API 免 SSH 运行模式**：支持通过 REST API 获取物理磁盘 SMART 健康度与 SSD 磨损寿命，实现 100% 免 SSH 零风险部署。
- 📢 **多渠道通知扩展**：原生支持 SMTP 邮件、Telegram Bot、飞书、钉钉、企业微信、Server酱、Bark 及 PushDeer。
- 🔐 **环境变量安全覆盖**：自动读取 `PVE_PASSWORD`、`PVE_HOST`、`TG_BOT_TOKEN`、`TG_CHAT_ID` 及 `SMTP_PASSWORD`，避免在物理镜像或 YAML 中暴露敏感凭据。

### 🔧 修复与优化 (Fixes & Refactoring)
- **防止重启后过度轮询**：修复了 Telegram 暂停告警发送 `/toggle_alert` 将 `alert_interval_seconds` 设为 `0` 后，服务重启时 APScheduler 强行以 1 秒高频执行任务的硬阻碍。现在 `alert_interval_seconds <= 0` 时自动在启动和运行时完全移除告警任务。
- **防止凭据打包进镜像**：更新 `.dockerignore` 强制排除 `config.yaml`、`.env` 及 `logs/`，并创建 `.gitignore` 防止凭据误提交。
- **通知渠道复位**：修复了 `NotificationManager` 重新加载配置时重复追加通知实例导致重复推送到邮箱/Telegram 的缺陷。
- **镜像 UTF-8 编码原生支持**：在 `Dockerfile` 中配置 `ENV PYTHONIOENCODING=utf-8` 和 `ENV LANG=C.UTF-8`。

---

## ⚡ PVE 版本兼容性与验证说明 (Compatibility & Verification)

| Proxmox VE 版本 | REST API 兼容性 | 物理磁盘 SMART API | USB 硬件扫描 API | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| **PVE 8.x** (Debian 12) | 100% 兼容 | 完美支持 (`/disks/list`) | 完美支持 (`/hardware/usb`) | ✅ 真实 PVE 8.x 主机实测验证 |
| **PVE 7.x** (Debian 11) | 100% 兼容 | 完美支持 (`/disks/list`) | 完美支持 (`/hardware/usb`) | 🧪 Mock REST API 自动化测试覆盖 |
| **PVE 6.x** | 部分兼容 | 支持 | 支持 | ⚠️ 建议升级到 7+ |

---

## 🔄 升级与回滚流程 (Upgrade & Rollback)

### 1. 平滑升级流程
```bash
# 1. 备份当前配置文件
cp config.yaml config.yaml.bak

# 2. 拉取/解压最新代码并重新构建 Docker 镜像
docker-compose down
docker-compose up -d --build

# 3. 检查运行日志
docker-compose logs -f pve-monitor
```

### 2. 紧急回滚流程
若新版本配置出现异常，可快速恢复上一个稳定版本：
```bash
docker-compose down
cp config.yaml.bak config.yaml
docker-compose up -d
```

---

## ⚠️ 已知问题与排错指南 (Known Issues & FAQ)

### 1. 为什么邮件中的表格在手机上会变成卡片列表？
* **答**：这是我们专门设计的 HTML 邮件双模（Hybrid Responsive）架构。在手机等窄屏幕（< 600px）设备上，6 列横向表格会被挤压变形，自动切换为满宽卡片列表能提供最佳阅读体验。

### 2. 开启 `verify_ssl: false` 会有什么影响？
* **答**：如果使用默认自签名 HTTPS 证书（如 `https://127.0.0.1:8006`），需要开启 `verify_ssl: false`。若需要极高安全性，建议为 PVE 配置 Let's Encrypt / ACME 证书并开启 `verify_ssl: true`。

### 3. Docker 容器提示 `UnicodeEncodeError` 怎么处理？
* **答**：我们在入口和脚本中已设置 `PYTHONIOENCODING=utf-8` 和 `sys.stdout.reconfigure()`，确保在任何终端环境下中英文与 Emoji 图标均能正常输出。
