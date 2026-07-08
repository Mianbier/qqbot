#!/usr/bin/env python3.11
"""一次性启动 keepalive + watchdog，然后退出，让子进程在后台跑"""
import subprocess, sys, os, time

scripts = [
    "/workspace/qqbot/keepalive.sh",
    "/workspace/qqbot/watchdog.sh",
]

procs = []
for s in scripts:
    p = subprocess.Popen(
        ["bash", s],
        stdout=open(os.devnull, "w"),
        stderr=open(os.devnull, "w"),
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # 彻底脱离终端
    )
    procs.append((s, p.pid))
    print(f"✅ {os.path.basename(s)} PID={p.pid}")

time.sleep(1)
# 检查都活着
for name, pid in procs:
    try:
        os.kill(pid, 0)
        print(f"  {name} 运行中")
    except OSError:
        print(f"  ❌ {name} 已退出")

print("启动完成，主进程退出，子进程继续运行")
