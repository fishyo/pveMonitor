FROM python:3.11-slim

# 安装 lm-sensors 与 smartmontools 工具，以便容器内能直接采集温度与磁盘 SMART 寿命
RUN apt-get update && apt-get install -y --no-install-recommends \
    lm-sensors \
    smartmontools \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV LANG=C.UTF-8

CMD ["python", "main.py"]
