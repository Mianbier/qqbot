#!/usr/bin/env bash
# QQbot 看门狗：每 60 秒检查机器人进程是否存活，挂了自动重启

LOG="/workspace/qqbot/watchdog.log"
BOT_SCRIPT="/workspace/qqbot/qqbot.py"
INTERVAL=60

log() { echo "[watchdog][$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "看门狗启动，检查间隔 ${INTERVAL}s, PID=$$"

while true; do
    sleep "$INTERVAL"

    # 检查 qqbot 进程是否还在
    if pgrep -f "python3.11.*qqbot.py" > /dev/null 2>&1; then
        # 还活着，静默
        continue
    fi

    log "⚠️  QQbot 进程丢失！尝试重启..."

    # 等几秒再试
    sleep 3
    if pgrep -f "python3.11.*qqbot.py" > /dev/null 2>&1; then
        log "进程已自行恢复"
        continue
    fi

    # 真正重启
    cd /workspace/qqbot && nohup python3.11 "$BOT_SCRIPT" >> qqbot.log 2>&1 &
    NEW_PID=$!
    log "✅ 已重启 QQbot, 新PID=$NEW_PID"

    sleep 10
    if pgrep -f "python3.11.*qqbot.py" > /dev/null 2>&1; then
        log "重启成功，进程运行中"
    else
        log "❌ 重启失败！请手动检查"
    fi
done
