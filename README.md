# Z-MAX 数据管线 · zmax-data-pipeline

Orin 真机采集 → MAC 转发 → 4090 落盘  
全 HTTP 自动化，无需 SCP/SSH/Agent 介入。

## 架构

```
Orin (192.168.23.10:8765)
  └─ FastAPI 网关
       ├─ POST /record/start?duration=30   开始采集
       ├─ GET  /record/status              查询进度
       ├─ GET  /record/latest              最新文件信息
       ├─ GET  /record/download            流式下载 tar.gz
       └─ GET  /health                     健康检查

MAC (cron 每 5 分钟)
  └─ zmax_cycle.sh
       ├─ POST Orin /record/start
       ├─ 等待 40 秒
       ├─ GET  Orin /record/download → 拉数据到本地
       ├─ POST datadrive.world/upload  → 推 4090
       └─ 结果自动发飞书群

4090 (datadrive.world)
  └─ POST /api/comfy/upload → 数据落盘 /root/datasets/
```

## 文件说明

| 文件 | 部署位置 | 职责 |
|------|---------|------|
| `orin_gateway.py` | Orin `~/.zmax/gateway/` | FastAPI 数据采集服务 |
| `mac_daemon.py` | Mac `hermes_gateway_mac/` | 常驻守护+心跳+转发 |
| `zmax_cycle.sh` | Mac `~/.hermes/scripts/` | 自动循环脚本(cron) |

## 依赖

- Orin: Python3 + FastAPI + uvicorn + ROS2 Humble
- Mac: Python3 + requests + bash
- 4090: 接受 multipart POST 上传文件
