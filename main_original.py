import os
import time
import subprocess
import RPi.GPIO as GPIO
import glob
import threading
import shutil
from datetime import datetime

# ================= ⚙️ 核心配置区 =================
USER_ID = "user4"
HALL_PIN = 26
RAM_DIR = "/dev/shm/live_videos"
OSS_DEST = "oss://foodpal-testuser-video/uploads/"
OSS_CONFIG = f"/home/{USER_ID}/.ossutilconfig"
#OSS_CONFIG = "/home/user4/.ossutilconfig"
MAX_FILES = 5
event_active = False

os.makedirs(RAM_DIR, exist_ok=True)
GPIO.setmode(GPIO.BCM)
GPIO.setup(HALL_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)


# ================= 🎥 视频引擎 (rpicam-vid 硬件编码) =================

def start_slicer():
    print("🧹 [清理环境] 停用后台干扰服务...")
    os.system("systemctl --user stop pipewire.socket pipewire.service wireplumber.service 2>/dev/null")
    os.system("sudo killall -9 rpicam-vid libcamera-vid ffmpeg 2>/dev/null")
    time.sleep(2)

    os.system(f"rm -f {RAM_DIR}/*.h264")

    # --segment 10000: 每 10 秒生成一个碎片段
    cmd = (
        "rpicam-vid -t 0 -n --inline --width 1920 --height 1080 --framerate 15 "
        "--codec h264 --segment 10000 "
        f"-o {RAM_DIR}/slice_%04d.h264 2>/dev/null"
    )
    return subprocess.Popen(cmd, shell=True)


# ================= ☁️ 后台任务 (优化版：仅上传 MP4) =================

def async_task(t_dir, eid):
    """
    负责：合并 -> 仅上传 MP4 -> 签名 -> 清理本地
    """
    print(f"☁️ [任务 {eid}] 正在合并视频...")

    # 1. 变量定义与修复
    list_p = os.path.join(t_dir, "list.txt")
    out_filename = f"event_{eid}.mp4"
    out_p = os.path.join(t_dir, out_filename)

    m_files = sorted(glob.glob(f"{t_dir}/slice_*.h264"))
    if not m_files:
        print(f"❌ [任务 {eid}] 未找到切片，跳过。")
        return

    # 2. 生成 FFmpeg 列表
    with open(list_p, "w") as f:
        for m in m_files:
            f.write(f"file '{m}'\n")

    # 3. 执行合并 (使用 faststart 优化网络播放)
    subprocess.run(
        f"ffmpeg -hide_banner -loglevel error -f concat -safe 0 -i {list_p} -c copy -movflags +faststart {out_p}",
        shell=True)

    print(f"☁️ [任务 {eid}] 正在上传视频至 OSS({USER_ID})...")

    # 4. 修改：指定只上传 MP4 文件到目标路径
    oss_target_url = f"{OSS_DEST}{USER_ID}/event_{eid}/{out_filename}"
    cmd = f"ossutil -c {OSS_CONFIG} cp {out_p} {oss_target_url}"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    # 5. 上传成功后的后续处理
    if res.returncode == 0:
        # 生成签名链接
        sign_cmd = f"ossutil -c {OSS_CONFIG} sign {oss_target_url} --timeout 3600"
        sign_res = subprocess.run(sign_cmd, shell=True, capture_output=True, text=True)

        if sign_res.returncode == 0:
            vlc_url = sign_res.stdout.strip().replace("%2F", "/")
            print("\n" + "✨" * 20)
            print(f"✅ [任务 {eid}] 上传成功！")
            print("🎬 VLC 预览链接:")
            print(vlc_url)
            print("✨" * 20 + "\n")

        # 彻底删除本地临时任务文件夹 (包含里面的 .h264 和 .txt)
        shutil.rmtree(t_dir, ignore_errors=True)
    else:
        print(f"❌ [任务 {eid}] 上传失败: {res.stderr}")


def memory_guard():
    """内存盘守护线程：循环覆盖旧切片，防止内存溢出"""
    global event_active
    while True:
        if not event_active:
            files = sorted(glob.glob(f"{RAM_DIR}/*.h264"))
            if len(files) > MAX_FILES:
                for f in files[:-MAX_FILES]:
                    try:
                        os.remove(f)
                    except:
                        pass
        time.sleep(5)


# ================= 🚀 主程序 =================

threading.Thread(target=memory_guard, daemon=True).start()
cam_proc = start_slicer()

try:
    last_state = GPIO.input(HALL_PIN)
    print("\n🚀 [FoodPal Pro 就绪] 监控中...")
    watchdog_timer = 0
    pre_files = []

    while True:
        current_state = GPIO.input(HALL_PIN)

        # 🚪 门被打开
        if current_state == GPIO.HIGH:
            if not event_active:
                print(f"\n🧲 {datetime.now().strftime('%H:%M:%S')} [触发] 冰箱门开启! ")
                event_active = True
                # 预录逻辑：取内存中最后的1个切片
                all_now = sorted(glob.glob(f"{RAM_DIR}/*.h264"))
                pre_files = all_now[-1:] if len(all_now) >= 2 else all_now
            elif watchdog_timer > 0:
                print(f"⚠️ {datetime.now().strftime('%H:%M:%S')} 监测到门被重新打开，倒计时重置，持续录制中...")
                watchdog_timer = 0

                # 🚪 门被关闭
        elif current_state == GPIO.LOW:
            if event_active and last_state == GPIO.HIGH:
                print(f"🚪 {datetime.now().strftime('%H:%M:%S')} 门已关闭，10秒后自动结算...")
                watchdog_timer = time.time()

            if event_active and watchdog_timer > 0:
                if time.time() - watchdog_timer >= 10:
                    time.sleep(3)  # 缓冲等待最后一段写入

                    print("\n⏳ 行为结束，正在整理素材...")
                    all_files = sorted(glob.glob(f"{RAM_DIR}/*.h264"))

                    files_to_merge = []
                    if pre_files and pre_files[0] in all_files:
                        start_idx = all_files.index(pre_files[0])
                        files_to_merge = all_files[start_idx:-1]
                    else:
                        files_to_merge = all_files[:-1]

                    if files_to_merge:
                        event_id = int(time.time())
                        staging_dir = f"/dev/shm/task_{event_id}"
                        os.makedirs(staging_dir, exist_ok=True)
                        # 拷贝需要的文件到临时任务区
                        for f in files_to_merge:
                            shutil.copy(f, staging_dir)

                        # 异步处理：不阻塞主监控循环
                        threading.Thread(target=async_task, args=(staging_dir, event_id), daemon=True).start()

                    event_active = False
                    watchdog_timer = 0
                    print("🚀 重回监控状态。")

        last_state = current_state
        time.sleep(0.1)

except KeyboardInterrupt:
    print("\n👋 停止监控...")
finally:
    if 'cam_proc' in locals():
        cam_proc.terminate()
    GPIO.cleanup()