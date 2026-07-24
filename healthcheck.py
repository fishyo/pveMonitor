import os
import sys
import time
import yaml

CONFIG_FILE = "config.yaml"
HEARTBEAT_FILE = "logs/heartbeat"

def check_health():
    # 1. 检查 config.yaml 是否存在且为有效 YAML 格式
    if not os.path.exists(CONFIG_FILE):
        print("HEALTHCHECK FAIL: config.yaml not found")
        sys.exit(1)
        
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
            if not isinstance(cfg, dict):
                print("HEALTHCHECK FAIL: config.yaml is invalid")
                sys.exit(1)
    except Exception as e:
        print(f"HEALTHCHECK FAIL: config.yaml parse error: {e}")
        sys.exit(1)

    # 2. 检查应用探针心跳文件 freshness (如果心跳文件超过 10 分钟未更新则判定判定死锁/崩溃)
    if os.path.exists(HEARTBEAT_FILE):
        try:
            mtime = os.path.getmtime(HEARTBEAT_FILE)
            elapsed = time.time() - mtime
            if elapsed > 600:  # 10 分钟无心跳刷新
                print(f"HEALTHCHECK FAIL: Heartbeat stale ({elapsed:.0f}s ago)")
                sys.exit(1)
        except Exception as e:
            print(f"HEALTHCHECK FAIL: Heartbeat check error: {e}")
            sys.exit(1)

    print("HEALTHCHECK OK: Service process is healthy")
    sys.exit(0)

if __name__ == "__main__":
    check_health()
