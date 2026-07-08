#!/usr/bin/env python3.11
"""一键重启：杀掉所有旧进程，重新启动 bot + keepalive + watchdog"""
import os, signal, subprocess, time

# 1. 杀旧进程
killed = 0
for pid_str in os.listdir("/proc"):
    if not pid_str.isdigit(): continue
    try:
        with open(f"/proc/{pid_str}/cmdline", "r") as f:
            cmdline = f.read().replace("\x00", " ")
        if "qqbot.py" in cmdline or "keepalive.sh" in cmdline or "watchdog.sh" in cmdline:
            os.kill(int(pid_str), signal.SIGTERM)
            killed += 1
            print(f"  💀 {pid_str}: {cmdline[:80]}")
    except: pass

time.sleep(2)
print(f"已清理 {killed} 个旧进程")

# 2. 启动 bot
print("\n启动 QQbot...")
os.chdir("/workspace/qqbot")
bot = subprocess.Popen(
    ["python3.11", "qqbot.py"],
    stdout=open("qqbot.log", "a"), stderr=subprocess.STDOUT,
    stdin=subprocess.DEVNULL, start_new_session=True
)
print(f"  ✅ qqbot PID={bot.pid}")
time.sleep(3)

# 3. 启动 keepalive + watchdog
print("启动守护进程...")
for name in ["keepalive.sh", "watchdog.sh"]:
    p = subprocess.Popen(
        ["bash", name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True
    )
    print(f"  ✅ {name} PID={p.pid}")

print("\n全部启动完成")
