#!/usr/bin/env python3
"""Orin Gateway — 数据+录制+下载+磁盘管理"""
import json, time, os, re, subprocess, signal, glob, io, tarfile, shutil
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI(title="Orin Gateway")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

JOINT_FILE = "/tmp/joints.json"
PORT = 8765
RECORD_PROC = None

# ─── 健康 ───
@app.get("/health")
def get_health():
    return {"online": True, "ts": time.time()}

# ─── 关节 ───
@app.get("/joints")
def get_joints():
    try:
        raw = open(JOINT_FILE).read().strip()
        vals = []
        for v in raw.split(","):
            v = v.strip().lstrip("- ")
            try: vals.append(round(float(v), 4))
            except: pass
        return {"joints": vals[:6], "ts": time.time()}
    except:
        return {"joints": [], "ts": 0}

# ─── 录制控制 ───
@app.post("/record/start")
def record_start(duration: int = 30):
    global RECORD_PROC
    if RECORD_PROC and RECORD_PROC.poll() is None:
        return {"status": "error", "message": "already recording"}
    ts = int(time.time())
    out = f"/home/tashan/.zmax/mcap/record_{ts}"
    # 显式话题列表 (-a 在模拟话题下发现不全, 改用固定列表)
    topics = "/real_joint_states /gripper_pos /robot/force_torque /realsense/color/image_raw /realsense/depth/image_rect_raw /joint_states /motion/active_states"
    cmd = f"bash -c 'source /opt/ros/humble/setup.bash && export ROS_DOMAIN_ID=0 && timeout {duration + 5} ros2 bag record -o {out} --max-bag-duration {duration} {topics}'"
    RECORD_PROC = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"status": "recording", "out": out, "duration": duration, "pid": RECORD_PROC.pid}

@app.post("/record/stop")
def record_stop():
    global RECORD_PROC
    if RECORD_PROC and RECORD_PROC.poll() is None:
        RECORD_PROC.terminate()
        try: RECORD_PROC.wait(5)
        except: RECORD_PROC.kill()
        return {"status": "stopped"}
    return {"status": "idle"}

@app.get("/record/status")
def record_status():
    global RECORD_PROC
    if RECORD_PROC and RECORD_PROC.poll() is None:
        return {"recording": True, "pid": RECORD_PROC.pid}
    return {"recording": False}

# ─── 最新录制信息 ───
@app.get("/record/latest")
def record_latest():
    dirs = sorted(glob.glob("/home/tashan/.zmax/mcap/record_*"), key=os.path.getmtime, reverse=True)
    if not dirs: return {"error": "no recordings"}
    d = dirs[0]
    name = os.path.basename(d)
    size_mb = round(sum(os.path.getsize(f) for f in glob.glob(f"{d}/*") if os.path.isfile(f)) / 1048576, 1)
    return {"dir": d, "name": name, "size_mb": size_mb}

# ─── 下载 ───
@app.get("/record/download")
def record_download():
    dirs = sorted(glob.glob("/home/tashan/.zmax/mcap/record_*"), key=os.path.getmtime, reverse=True)
    if not dirs: return {"error": "no recordings"}
    d = dirs[0]
    def iter_tar():
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for f in glob.glob(f"{d}/**", recursive=True):
                if os.path.isfile(f): tar.add(f, arcname=os.path.relpath(f, os.path.dirname(d)))
        buf.seek(0)
        yield from buf
    name = os.path.basename(d)
    return StreamingResponse(iter_tar(), media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{name}.tar.gz"'})
    def iter_tar():
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for f in glob.glob(f"{d}/**", recursive=True):
                if os.path.isfile(f): tar.add(f, arcname=os.path.relpath(f, os.path.dirname(d)))
        buf.seek(0)
        yield from buf
    name = os.path.basename(d)
    return StreamingResponse(iter_tar(), media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{name}.tar.gz"'})

# ─── 磁盘监控 ───
@app.get("/disk")
def get_disk():
    dirs = sorted(glob.glob("/tmp/zmax_*"), key=os.path.getmtime)
    total_mb = 0; oldest = None
    for d in dirs:
        s = sum(os.path.getsize(f) for f in glob.glob(f"{d}/*") if os.path.isfile(f))
        total_mb += s
        if oldest is None: oldest = {"dir": d, "size_mb": round(s / 1048576, 1)}
    return {"total_mb": round(total_mb / 1048576, 1), "count": len(dirs), "over_1g": total_mb > 1048576000, "oldest": oldest}

# ─── 清理旧数据 ───
MCAP_DIR = os.path.expanduser("~/.zmax/mcap")
MAX_MCAP_MB = 1_000  # mcap 上限 1GB, 超了自动清理

@app.post("/record/cleanup")
def cleanup(n: int = 10):
    """保留最近 n 轮, 删除更旧的 mcap; 返回释放空间"""
    dirs = sorted(glob.glob(f"{MCAP_DIR}/record_*"), key=os.path.getmtime)
    if len(dirs) <= n: return {"deleted": 0, "remaining": len(dirs), "total_mb": _mcap_mb()}
    deleted = 0; freed_mb = 0
    for d in dirs[:-n]:
        s = sum(os.path.getsize(f) for f in glob.glob(f"{d}/*") if os.path.isfile(f))
        freed_mb += s; shutil.rmtree(d, ignore_errors=True); deleted += 1
    return {"deleted": deleted, "freed_mb": round(freed_mb / 1048576, 1), "remaining": n, "total_mb": _mcap_mb()}

def _mcap_mb() -> float:
    total = 0
    for d in glob.glob(f"{MCAP_DIR}/record_*"):
        for f in glob.glob(f"{d}/*"):
            if os.path.isfile(f): total += os.path.getsize(f)
    return round(total / 1048576, 1)

@app.get("/disk/guard")
def disk_guard():
    """磁盘守护: mcap 超上限自动清理 (1GB上限保留10轮, 更多旧轮直接删)"""
    total_mb = _mcap_mb()
    if total_mb > MAX_MCAP_MB:
        # 上限1GB: 保留10轮(约1GB), 其余全删
        keep = 10
        r = cleanup(keep)
        return {"guard": "triggered", "before_mb": total_mb, "after_mb": _mcap_mb(), "limit_mb": MAX_MCAP_MB, "keep_rounds": keep, "cleaned": r}
    return {"guard": "ok", "total_mb": total_mb, "limit_mb": MAX_MCAP_MB}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
