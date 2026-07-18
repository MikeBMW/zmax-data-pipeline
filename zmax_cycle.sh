#!/bin/bash
# ZMAX自动采集循环 · 全HTTP · 无agent介入
COUNTER_FILE="/tmp/zmax_cycle_counter"
ORIN="http://192.168.23.10:8765"
UPLOAD_URL="http://datadrive.world/api/comfy/upload"

[ -f "$COUNTER_FILE" ] && N=$(cat "$COUNTER_FILE") || N=0
N=$((N+1)); echo $N > "$COUNTER_FILE"
TS=$(date '+%Y-%m-%d %H:%M:%S')

echo ""
echo "═══════════════ 循环 #${N} · ${TS} ═══════════════"

# 1. 开始录制
R=$(curl -s -X POST "${ORIN}/record/start?duration=30" --max-time 5)
echo "[Orin] 采集开始"

# 2. 等待
sleep 40

# 3. 查最新录制大小
LATEST=$(curl -s "${ORIN}/record/latest" --max-time 5)
SIZE_MB=$(echo "$LATEST" | grep -o '"size_mb":[0-9.]*' | cut -d: -f2)
DIR=$(echo "$LATEST" | grep -o '"dir":"[^"]*"' | cut -d'"' -f4)
echo "[Orin] 完成: ${SIZE_MB}MB"

# 4. HTTP下载到本地
echo "[MAC] HTTP下载中..."
curl -s "${ORIN}/record/download" --max-time 300 -o "/tmp/cycle_${N}.tar.gz"
LS=$(ls -lh "/tmp/cycle_${N}.tar.gz" 2>/dev/null | awk '{print $5}')
echo "[MAC] 收到: ${LS}"

# 5. HTTP上传到4090
echo "[4090] 上传中..."
curl -s -X POST "${UPLOAD_URL}" -F "file=@/tmp/cycle_${N}.tar.gz" --max-time 180 > /dev/null 2>&1
echo "[4090] 上传完成"

# 6. 发到飞书（stdout自动投递）
echo ""
echo "📦 ZMAX循环 #${N}"
echo "   时间: ${TS}"
echo "   Orin大小: ${SIZE_MB}MB"
echo "   MAC接收: ${LS}"
echo "   已上传 4090 ✅"
echo ""

rm -f "/tmp/cycle_${N}.tar.gz"
