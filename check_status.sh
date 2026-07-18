#!/bin/bash
# 小芳状态检查 · 一行命令
# 用法: bash <(curl -s http://127.0.0.1:8766/status.sh) 或直接运行本文件

echo ""
echo "══════════ 小芳状态 ══════════"

# 1. 守护进程
if ps aux | grep -q "[x]iaofang_daemon.py"; then
    PID=$(ps aux | grep "[x]iaofang_daemon" | awk '{print $2}')
    UPTIME=$(ps aux | grep "[x]iaofang_daemon" | awk '{print $9}')
    echo "  🟢 守护进程  PID=$PID  启动=$UPTIME"
else
    echo "  🔴 守护进程  未运行"
fi

# 2. 转发器状态
FWD=$(curl -s --max-time 3 http://127.0.0.1:8769/ 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "  🟢 转发器 :8769  响应=$FWD"
else
    echo "  🔴 转发器 :8769  无响应"
fi

# 3. Orin 连接（直接检查服务器是否可达，不依赖文件时间戳）
ORIN_CHECK=$(curl -s --max-time 3 http://192.168.23.10:8765/record/status 2>/dev/null)
if echo "$ORIN_CHECK" | grep -q "recording"; then
    echo "  🟢 Orin 连接  在线"
else
    echo "  🔴 Orin 连接  离线"
fi

# 4. 录制状态
REC=$(curl -s --max-time 3 http://127.0.0.1:8769/status 2>/dev/null | grep -o '"recording":true')
if [ -n "$REC" ]; then
    echo "  🟢 录制状态  采集中"
else
    echo "  ⚪ 录制状态  空闲"
fi

# 5. 心跳
HB=$(curl -s --max-time 5 -X POST http://datadrive.world/api/comfy/api/mac/heartbeat -H "Content-Type: application/json" -d '{"orin":{"online":true}}' 2>/dev/null | grep -o '"ok"')
if [ -n "$HB" ]; then
    echo "  🟢 心跳 4090  正常"
else
    echo "  🔴 心跳 4090  失败"
fi

# 6. 工程
if [ -d /Users/mikeni/zmax-data-pipeline/.git ]; then
    VER=$(cd /Users/mikeni/zmax-data-pipeline && git log --oneline -1 2>/dev/null)
    echo "  🟢 数据管线   $VER"
fi

echo ""
echo "  检查时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "══════════════════════════════"
echo ""
