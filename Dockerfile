FROM python:3.11-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    bash \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Playwright 浏览器
RUN playwright install --with-deps chromium

# 复制代码
WORKDIR /app
COPY . .

# 创建数据目录
RUN mkdir -p /app/data

# 启动机器人
CMD ["python3.11", "qqbot.py"]
