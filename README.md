# Z-MAX 数据管线 · zmax-data-pipeline

> 小芳维护 · pipe 工程  
> 版本: `v2.4.1` · 2026-07-19

## 架构

```
Orin (192.168.23.66:8765)          MAC (192.168.23.1)              4090 (datadrive.world)
┌────────────────────┐            ┌──────────────────┐            ┌────────────────────┐
│ FastAPI 网关       │            │ 转发器            │            │ ComfyUI 后端        │
│ POST /record/start │ ←──HTTP── │ mac_forwarder.sh  │ ──HTTP──→ │ POST /api/comfy/    │
│ GET /record/status │ 检测新包   │ 每5秒轮询Orin     │  上传      │ upload              │
│ GET /record/latest │            │ SCP下载→POST上传  │            │ 数据落盘→触发训练    │
│ GET /record/download│           │ 上传后删除Orin包  │            │                     │
│ GET /health        │            │                    │            │                     │
└────────────────────┘            └──────────────────┘            └────────────────────┘
         ↑                                ↑
  orin_collect.sh                     mac_heartbeat.py
  5秒循环录制→压缩tar.gz              每5秒上报Orin状态
  缓冲最多10个包                       recording/false
```

## 部署指令（Mac 终端执行）

### 一键部署 Orin 全套

```bash
cd /Users/mikeni/zmax-data-pipeline
bash deploy_orin.sh
```

自动完成（全部用本地代码，不从 GitHub 下载）：
1. 创建 `~/mcap/` `~/.zmax/` 目录
2. SCP 本地 `orin_gateway.py` 到 Orin → 启动 FastAPI :8765
3. 启动机器人（若未启动）
4. 部署 `orin_collect.sh` → 启动 5 秒循环录制
5. 输出验证结果

### 启动 MAC 心跳

```bash
cd /Users/mikeni/lerobot-smolvla-lew
.venv/bin/python3 tools/mac_heartbeat.py &
```

### 启动 MAC 转发器

```bash
bash /Users/mikeni/zmax-data-pipeline/mac_forwarder.sh &
```

每 5 秒检测 Orin `~/mcap/record_*.tar.gz` 新文件 → SCP 到本地 → POST 上传 4090 → 删除 Orin 文件。

## 检查运行状态

```bash
# Orin 状态
curl -s http://192.168.23.66:8765/health
curl -s http://192.168.23.66:8765/record/status
curl -s http://192.168.23.66:8765/disk

# 后端状态
curl -s http://datadrive.world/api/comfy/status

# MAC 进程
ps aux | grep -E "mac_heartbeat|mac_forwarder" | grep -v grep
```

## 停止

```bash
# 停止转发器
pkill -f mac_forwarder
# 停止心跳
pkill -f mac_heartbeat
# 停止 Orin 采集
ssh tashan@192.168.23.66 "pkill -f orin_collect; pkill -f 'ros2 bag'"
# 停止 FastAPI
ssh tashan@192.168.23.66 "kill \$(lsof -ti:8765)"
```

## Orin 存储策略

- 路径: `~/mcap/record_时间戳.tar.gz`
- 录制时长: 5 秒
- 缓冲区: 最多 10 个包
- 超出则删除最旧

## 文件说明

| 文件 | 部署位置 | 用途 |
|------|---------|------|
| `orin_gateway.py` | Orin `~/.zmax/` | FastAPI 录制/健康/磁盘端点 |
| `orin_collect.sh` | Orin `~/.zmax/` | 5秒录制循环 |
| `deploy_orin.sh` | MAC 本地 | 一键部署 Orin |
| `mac_forwarder.sh` | MAC 本地 | 检测Orin新包→上传4090 |
| `check_status.sh` | MAC 本地 | 一行状态检查 |
