#!/usr/bin/env bash
# 沙箱保活心跳：每 5 分钟进行一次网络活动 + 写文件，尽量延缓休眠

LOG="/workspace/qqbot/keepalive.log"
INTERVAL=20   # 20秒

log() { echo "[keepalive][$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "保活心跳启动，间隔 ${INTERVAL}s, PID=$$"

while true; do
    sleep "$INTERVAL"

    # 1. 网络心跳：ping 百度和 QQ API
    curl -s -m 10 -o /dev/null "https://www.baidu.com" 2>/dev/null && \
        log "🌐 百度 OK" || log "❌ 百度不通"

    curl -s -m 10 -o /dev/null "https://api.sgroup.qq.com" 2>/dev/null && \
        log "🌐 QQ API OK" || log "❌ QQ API不通"

    # 2. 写时间戳文件
    date '+%s' > /workspace/qqbot/.heartbeat 2>/dev/null

    # 3. 给 QQbot 写日志表示存活
    log "💓 心跳 (uptime: $(cat /proc/uptime 2>/dev/null | cut -d' ' -f1)s)"
done
