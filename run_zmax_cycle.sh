#!/bin/bash
# Z-MAX 数据采集闭环 (cron 自动执行)
# 退出码: 10=Orin离线(静默) 11=机器人未就绪(静默) 12=无录制 0=完成
set -u

IP=$(printf '%d.%d.%d.%d' 192 168 23 66)
GW="http://${IP}:8765"
SSH="ssh -o ConnectTimeout=8 -o BatchMode=yes -o StrictHostKeyChecking=accept-new tashan@${IP}"

# 1. Orin 网关在线?
H=$(curl -s --max-time 5 "${GW}/health" 2>/dev/null)
if ! echo "$H" | grep -q "online"; then
  echo "GATEWAY_OFFLINE" >&2
  exit 10
fi
echo "HEALTH: $H"

# 2. 机器人就绪? (加 timeout 防止 topic 无消息时挂死)
R=$($SSH "timeout 20 bash -c 'source /opt/ros/humble/setup.bash && ros2 topic echo /motion/initialization_complete --once 2>&1'" 2>&1)
if ! echo "$R" | grep -q "data: true"; then
  echo "ROBOT_NOT_READY: $R" >&2
  exit 11
fi
echo "ROBOT_READY: $(echo "$R" | grep 'data:')"

# 3. 采集 20 秒
echo "REC_START: $(curl -s -X POST "${GW}/record/start?duration=20")"

# 4. 等 30 秒后取最新包并上传
sleep 30
LATEST=$($SSH "ls -td /home/tashan/.zmax/mcap/record_*/ | head -1" 2>/dev/null | tr -d '\r')
if [ -z "$LATEST" ]; then
  echo "NO_RECORDING" >&2
  exit 12
fi
echo "LATEST: $LATEST"
$SSH "python3 ~/.zmax/upload_data_v2.py $LATEST" 2>&1
echo "CYCLE_DONE"
