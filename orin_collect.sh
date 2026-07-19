#!/bin/bash
# Orin 持续录制循环 · 录5秒→压缩→等待上传
# 从 GitHub 下载: wget -q -O orin_collect.sh https://raw.githubusercontent.com/MikeBMW/zmax-data-pipeline/main/orin_collect.sh && bash orin_collect.sh

MCAP_DIR="$HOME/mcap"
ROS_WS="$HOME/07151/tashan_robot_so_20260715_145343_07f342b_aarch64"

mkdir -p "$MCAP_DIR"
cd "$MCAP_DIR" || exit 1

echo "=== Orin 采集循环启动 ==="
echo "存储: $MCAP_DIR"
echo "ROS2: $ROS_WS"

while true; do
    TS=$(date +%s)
    source /opt/ros/humble/setup.bash
    source "$ROS_WS/install/setup.bash"
    export ROS_DOMAIN_ID=23

    timeout 10 ros2 bag record -o "record_${TS}" --max-bag-duration 5 -a 2>&1 > /dev/null

    tar czf "record_${TS}.tar.gz" "record_${TS}/" 2>/dev/null && rm -rf "record_${TS}/"
    echo "$(date '+%H:%M:%S') record_${TS}.tar.gz 完成"

    # 缓冲区超10个删最旧
    PACKS=(record_*.tar.gz)
    if [ ${#PACKS[@]} -gt 10 ]; then
        OLD="${PACKS[0]}"
        rm -f "$OLD"
        echo "  删除旧包: $OLD"
    fi

    sleep 2
done
