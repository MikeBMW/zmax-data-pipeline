#!/bin/bash
# MAC 转发器 · 检测Orin新包→下载→上传4090→删除
# 用法: bash mac_forwarder.sh

ORIN_SSH="tashan@192.168.23.66"
ORIN_MCAP="/home/tashan/.zmax/mcap"
UPLOAD_URL="http://datadrive.world/api/comfy/upload"
HISTORY_FILE="/tmp/mac_forwarder_history.txt"
MAX_MB=100

touch "$HISTORY_FILE"

echo "=== MAC 转发器启动 ==="

while true; do
    # 缓冲保护: MAC 本地缓冲超100MB则清理
    LOCAL_MB=$(du -sm /tmp/ul.tar.gz /tmp/cycle_*.tar.gz 2>/dev/null | awk '{s+=$1} END {print s+0}')
    if [ "$LOCAL_MB" -gt "$MAX_MB" ]; then
        echo "$(date '+%H:%M:%S') ⚠️ MAC缓冲${LOCAL_MB}MB超限, 清理旧文件"
        rm -f /tmp/ul.tar.gz /tmp/cycle_*.tar.gz
    fi

    # Orin缓冲保护: Orin端超100MB则删最旧
    ORIN_MB=$(ssh "$ORIN_SSH" "du -sm $ORIN_MCAP/ 2>/dev/null | awk '{print \$1}'" 2>/dev/null)
    if [ "${ORIN_MB:-0}" -gt "$MAX_MB" ]; then
        echo "$(date '+%H:%M:%S') ⚠️ Orin缓冲${ORIN_MB}MB超限, 删除最旧包"
        ssh "$ORIN_SSH" "ls -t $ORIN_MCAP/record_*.tar.gz 2>/dev/null | tail -1 | xargs rm -f" > /dev/null 2>&1
    fi

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
