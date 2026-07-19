#!/bin/bash
# MAC 转发器 · 检测Orin新包→下载→上传4090→删除
# 用法: bash mac_forwarder.sh

ORIN_SSH="tashan@192.168.23.66"
ORIN_MCAP="/home/tashan/mcap"
UPLOAD_URL="http://datadrive.world/api/comfy/upload"
HISTORY_FILE="/tmp/mac_forwarder_history.txt"

touch "$HISTORY_FILE"

echo "=== MAC 转发器启动 ==="

while true; do
    # 查找Orin上未上传的包
    for F in $(ssh "$ORIN_SSH" "ls $ORIN_MCAP/record_*.tar.gz 2>/dev/null" 2>/dev/null); do
        NAME=$(basename "$F")
        # 跳过已上传的
        grep -q "$NAME" "$HISTORY_FILE" 2>/dev/null && continue

        echo "$(date '+%H:%M:%S') 转发 $NAME"
        
        # 下载
        scp "$ORIN_SSH:$F" /tmp/ul.tar.gz > /dev/null 2>&1
        
        # 上传到4090
        curl -s -X POST "$UPLOAD_URL" \
            -F "file=@/tmp/ul.tar.gz" \
            --max-time 300 > /dev/null 2>&1
        HTTP_CODE=$?
        
        # 无论上传成功与否, 记录已处理并从Orin删除
        echo "$NAME" >> "$HISTORY_FILE"
        ssh "$ORIN_SSH" "rm -f $F" > /dev/null 2>&1
        rm -f /tmp/ul.tar.gz
        
        echo "  → 已完成 (HTTP=$HTTP_CODE)"
    done
    
    sleep 5
done
