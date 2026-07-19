# Z-MAX 数据管线 · zmax-data-pipeline

> 小芳维护 · v2.3-auto-0719

## 架构

```
Orin (192.168.23.10:8765)  ─HTTP─→  MAC  ─HTTP─→  4090 (datadrive.world)
  POST /record/start              自动采集循环          POST /api/comfy/upload
  GET  /record/status             每 5 分钟            数据落盘 → 训练触发
  GET  /record/download           心跳每 5 秒
```

## 启动采集守护

```bash
# 1. 进主工程
cd /Users/mikeni/lerobot-smolvla-lew

# 2. 切到 main 分支
git checkout main
git pull origin main

# 3. 运行自动采集（后台常驻）
python3 tools/zmax_auto_collector.py &

# 或前台运行:
python3 tools/zmax_auto_collector.py
```

## 检查运行状态

```bash
# 一行命令检查全部
bash /Users/mikeni/zmax-data-pipeline/check_status.sh

# 输出示例:
#   🟢 守护进程  PID=83851
#   🟢 转发器 :8769
#   🟢 Orin 连接  在线
#   🟢 录制状态  采集中
#   🟢 心跳 4090  正常
```

## 守护进程管理

```bash
# 查看采集日志
ps aux | grep zmax_auto
tail -f ~/zmax_loop/*.log

# 停止采集
kill $(pgrep -f zmax_auto_collector)

# 重启采集
python3 tools/zmax_auto_collector.py &
```

## 手动触发一次采集

```bash
curl -s -X POST "http://192.168.23.10:8765/record/start?duration=30"
sleep 35
curl -s "http://192.168.23.10:8765/record/latest"
```

## 文件说明

| 文件 | 用途 |
|------|------|
| `orin_gateway.py` | Orin FastAPI 数据服务（部署在 Orin） |
| `mac_daemon.py` | MAC 常驻守护（心跳+转发） |
| `zmax_cycle.sh` | 自动采集循环脚本（cron 调用） |
| `check_status.sh` | 一行状态检查 |
| `tools/zmax_auto_collector.py` | 自动采集守护（循环录制+上传） |

## 版本

当前: `v2.3-auto-0719` · 2026-07-19
