#!/usr/bin/env python3
"""珞石机械臂控制器只读体检脚本 · Orin 运行
============================================
通过珞石官方 xCoreSDK (TCP:6666) 查询机械臂状态, 全程只读,
不干扰产线 robot_driver 连接。

用法 (Orin, 需 source ROS + 有 xCoreSDK):
  python3 rokae_query.py              # 全量体检
  python3 rokae_query.py info         # 只查基本信息
  python3 rokae_query.py power        # 只查上电状态
  python3 rokae_query.py events       # 查事件/报警(尝试)

安全: 只调用查询接口, 不发任何运动指令, 不设置任何参数,
      查询完立即断开。与产线连接可共存。
"""
import sys
import json
import argparse

# xCoreSDK 路径 (Orin 07171 产线安装位置)
SDK_PATHS = [
    "/home/tashan/07171/tashan_robot_so_20260717_110359_a4e6adc_aarch64/install/robot_driver/lib/python3.10/site-packages/robot_driver/rokae/xcoresdk_python",
    "/home/tashan/.zmax/rokae_sdk",  # 备用
]

ROBOT_IP = "192.168.23.160"
LOCAL_IP = "192.168.23.66"  # Orin


def _load_sdk():
    for p in SDK_PATHS:
        sys.path.insert(0, p)
        try:
            from Release.linux.arm import xCoreSDK_python as sdk
            return sdk
        except Exception:
            try:
                from Release.linux import xCoreSDK_python as sdk
                return sdk
            except Exception:
                continue
    raise RuntimeError("找不到 xCoreSDK, 检查 SDK_PATHS")


def query_info(sdk):
    """基本信息: 型号/固件/SN/关节数"""
    r = sdk.xMateRobot()
    ec = {}
    r.connectToRobot(ROBOT_IP, LOCAL_IP)
    info = r.robotInfo(ec)
    result = {
        "model": str(getattr(info, "type", "?")),
        "version": str(getattr(info, "version", "?")),
        "joints": str(getattr(info, "joint_num", "?")),
        "device_id": str(getattr(info, "id", "?")),
    }
    # 上电状态
    try:
        ps = r.powerState(ec)
        result["power"] = str(ps)
    except Exception:
        result["power"] = "unknown"
    r.disconnectFromRobot(ec)
    return result


def query_events(sdk):
    """尝试查询事件/报警 (签名可能需要额外参数)"""
    r = sdk.xMateRobot()
    ec = {}
    r.connectToRobot(ROBOT_IP, LOCAL_IP)
    result = {}
    for name in ["queryEventInfo", "queryControllerLog"]:
        try:
            v = getattr(r, name)(ec)
            result[name] = str(v)
        except Exception as e:
            result[name] = f"签名需要参数: {str(e)[:60]}"
    r.disconnectFromRobot(ec)
    return result


def main():
    ap = argparse.ArgumentParser(description="珞石机械臂只读体检")
    ap.add_argument("mode", nargs="?", default="all", choices=["all", "info", "power", "events"])
    args = ap.parse_args()

    sdk = _load_sdk()
    print(f"🔧 珞石控制器: {ROBOT_IP}:6666 (只读模式, 不干扰产线)")

    report = {}
    if args.mode in ("all", "info"):
        info = query_info(sdk)
        report["info"] = info
        print(f"\n📋 机械臂信息:")
        print(f"   型号:     {info['model']}")
        print(f"   固件:     {info['version']}")
        print(f"   关节数:   {info['joints']}")
        print(f"   设备ID:   {info['device_id']}")
        print(f"   上电:     {info['power']}")

    if args.mode in ("all", "power"):
        info = query_info(sdk)
        print(f"\n⚡ 上电状态: {info['power']}")

    if args.mode in ("all", "events"):
        ev = query_events(sdk)
        report["events"] = ev
        print(f"\n⚠️ 事件/报警: {json.dumps(ev, ensure_ascii=False, indent=2)}")

    # 保存报告
    with open("/tmp/rokae_query_report.json", "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n💾 报告: /tmp/rokae_query_report.json")
    print("✅ 完成 (全程只读, 未发运动指令)")


if __name__ == "__main__":
    main()
