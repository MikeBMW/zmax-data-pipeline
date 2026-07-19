#!/bin/bash
# Z-MAX Orin 完整部署脚本 · 从 Mac 执行
# 用 法: bash deploy_orin.sh
# 前置: pipe 工程已克隆, Orin 已开机联网(192.168.23.66)

ORIN="tashan@192.168.23.66"
ORIN_HOME="/home/tashan"
PIPE_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "══════════ Z-MAX Orin 部署 ══════════"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 第1步: 部署 FastAPI 网关
echo ">>> [1/5] 部署 FastAPI 网关..."
ssh "$ORIN" "mkdir -p $ORIN_HOME/.zmax $ORIN_HOME/mcap"
scp "$PIPE_DIR/orin_gateway.py" "$ORIN:$ORIN_HOME/.zmax/orin_gateway.py"
ssh "$ORIN" "kill -9 \$(lsof -ti:8765) 2>/dev/null; nohup python3 $ORIN_HOME/.zmax/orin_gateway.py > /tmp/gw.log 2>&1 &"
sleep 5
HEALTH=$(ssh "$ORIN" "curl -s http://127.0.0.1:8765/health")
echo "  FastAPI: $HEALTH"

# 第2步: 启动机器人（如果还没启动）
echo ">>> [2/5] 启动机器人..."
TOPICS=$(ssh "$ORIN" "source /opt/ros/humble/setup.bash && export ROS_DOMAIN_ID=23 && timeout 10 ros2 topic list 2>/dev/null | wc -l")
if [ "$TOPICS" -gt 0 ] 2>/dev/null; then
    echo "  已运行（${TOPICS}话题），跳过"
else
    echo "  启动中，等待30秒..."
    ssh "$ORIN" "cd $ORIN_HOME/07151/tashan_robot_so_20260715_145343_07f342b_aarch64 && source /opt/ros/humble/setup.bash && source install/setup.bash && export ROS_DOMAIN_ID=23 && timeout 40 nohup ros2 launch launch/start.launch.py project:=sr5_guangmokuai_100gAOI > /tmp/rl.log 2>&1 &"
    sleep 30
    TOPICS=$(ssh "$ORIN" "source /opt/ros/humble/setup.bash && export ROS_DOMAIN_ID=23 && timeout 10 ros2 topic list 2>/dev/null | wc -l")
    echo "  话题数: $TOPICS"
fi

# 第3步: 部署采集脚本
echo ">>> [3/5] 部署采集脚本..."
scp "$PIPE_DIR/orin_collect.sh" "$ORIN:$ORIN_HOME/.zmax/orin_collect.sh"
ssh "$ORIN" "chmod +x $ORIN_HOME/.zmax/orin_collect.sh"

# 第4步: 启动持续采集
echo ">>> [4/5] 启动持续采集..."
ssh "$ORIN" "nohup bash $ORIN_HOME/.zmax/orin_collect.sh > /tmp/collect.log 2>&1 &"
sleep 8

# 第5步: 验证
echo ">>> [5/5] 验证..."
echo ""
echo "══════════ 状态 ══════════"
ssh "$ORIN" "echo '  FastAPI:' && curl -s http://127.0.0.1:8765/health && echo '' && echo '  录制状态:' && curl -s http://127.0.0.1:8765/record/status && echo '' && echo '  数据包:' && ls $ORIN_HOME/mcap/record_*.tar.gz 2>/dev/null | wc -l"
echo ""
echo "部署完成 ✅"
