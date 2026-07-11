import glob
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import RPi.GPIO as GPIO

# ================= Configuration =================
USER_ID = os.getenv("FOOMIE_USER_ID", "user4")
HALL_PIN = int(os.getenv("FOOMIE_HALL_PIN", "26"))
RAM_DIR = Path(os.getenv("FOOMIE_RAM_DIR", "/dev/shm/live_videos"))
OSS_DEST = os.getenv("FOOMIE_OSS_DEST", "oss://foodpal-testuser-video/uploads/")
OSS_CONFIG = Path(
    os.getenv("FOOMIE_OSS_CONFIG", f"/home/{USER_ID}/.ossutilconfig")
)
MAX_FILES = int(os.getenv("FOOMIE_MAX_FILES", "5"))
SEGMENT_MS = int(os.getenv("FOOMIE_SEGMENT_MS", "10000"))
CLOSE_DELAY_SECONDS = int(os.getenv("FOOMIE_CLOSE_DELAY_SECONDS", "10"))

EVENT_ACTIVE = False

RAM_DIR.mkdir(parents=True, exist_ok=True)
GPIO.setmode(GPIO.BCM)
GPIO.setup(HALL_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)


def run_command(command: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess:
    """Run a command without invoking a shell."""
    return subprocess.run(
        command,
        check=False,
        capture_output=capture_output,
        text=True,
    )


def start_slicer() -> subprocess.Popen:
    """Start continuous H.264 capture and write fixed-length segments to RAM."""
    print("🧹 [初始化] 清理残留摄像进程...")
    run_command(["sudo", "killall", "-9", "rpicam-vid", "libcamera-vid", "ffmpeg"])
    time.sleep(2)

    for file_path in RAM_DIR.glob("*.h264"):
        file_path.unlink(missing_ok=True)

    command = [
        "rpicam-vid",
        "-t",
        "0",
        "-n",
        "--inline",
        "--width",
        "1920",
        "--height",
        "1080",
        "--framerate",
        "15",
        "--codec",
        "h264",
        "--segment",
        str(SEGMENT_MS),
        "-o",
        str(RAM_DIR / "slice_%04d.h264"),
    ]
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def async_task(task_dir: Path, event_id: int) -> None:
    """Merge captured slices, upload the MP4 to OSS, sign it, and clean local files."""
    print(f"☁️ [任务 {event_id}] 正在合并视频...")

    list_path = task_dir / "list.txt"
    output_name = f"event_{event_id}.mp4"
    output_path = task_dir / output_name

    media_files = sorted(task_dir.glob("slice_*.h264"))
    if not media_files:
        print(f"❌ [任务 {event_id}] 未找到切片，跳过。")
        return

    with list_path.open("w", encoding="utf-8") as file_handle:
        for media_file in media_files:
            file_handle.write(f"file '{media_file}'\n")

    merge_result = run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        capture_output=True,
    )
    if merge_result.returncode != 0:
        print(f"❌ [任务 {event_id}] 视频合并失败: {merge_result.stderr}")
        return

    print(f"☁️ [任务 {event_id}] 正在上传视频至 OSS ({USER_ID})...")
    oss_target_url = f"{OSS_DEST.rstrip('/')}/{USER_ID}/event_{event_id}/{output_name}"

    upload_result = run_command(
        ["ossutil", "-c", str(OSS_CONFIG), "cp", str(output_path), oss_target_url],
        capture_output=True,
    )
    if upload_result.returncode != 0:
        print(f"❌ [任务 {event_id}] 上传失败: {upload_result.stderr}")
        return

    sign_result = run_command(
        ["ossutil", "-c", str(OSS_CONFIG), "sign", oss_target_url, "--timeout", "3600"],
        capture_output=True,
    )
    if sign_result.returncode == 0:
        preview_url = sign_result.stdout.strip().replace("%2F", "/")
        print("\n" + "✨" * 20)
        print(f"✅ [任务 {event_id}] 上传成功！")
        print("🎬 一小时预览链接:")
        print(preview_url)
        print("✨" * 20 + "\n")
    else:
        print(f"⚠️ [任务 {event_id}] 上传成功，但签名失败: {sign_result.stderr}")

    shutil.rmtree(task_dir, ignore_errors=True)


def memory_guard() -> None:
    """Keep only recent idle segments to prevent RAM-disk overflow."""
    global EVENT_ACTIVE
    while True:
        if not EVENT_ACTIVE:
            files = sorted(RAM_DIR.glob("*.h264"))
            if len(files) > MAX_FILES:
                for file_path in files[:-MAX_FILES]:
                    try:
                        file_path.unlink()
                    except OSError:
                        pass
        time.sleep(5)


def main() -> None:
    global EVENT_ACTIVE

    threading.Thread(target=memory_guard, daemon=True).start()
    camera_process = start_slicer()

    try:
        last_state = GPIO.input(HALL_PIN)
        print("\n🚀 [Foomie Hardware Collector 就绪] 监控中...")
        watchdog_timer = 0.0
        pre_files: list[Path] = []

        while True:
            current_state = GPIO.input(HALL_PIN)

            if current_state == GPIO.HIGH:
                if not EVENT_ACTIVE:
                    print(f"\n🧲 {datetime.now().strftime('%H:%M:%S')} [触发] 冰箱门开启！")
                    EVENT_ACTIVE = True
                    all_now = sorted(RAM_DIR.glob("*.h264"))
                    pre_files = all_now[-1:] if all_now else []
                elif watchdog_timer > 0:
                    print(
                        f"⚠️ {datetime.now().strftime('%H:%M:%S')} "
                        "检测到门重新打开，倒计时重置，继续录制..."
                    )
                    watchdog_timer = 0.0

            elif current_state == GPIO.LOW:
                if EVENT_ACTIVE and last_state == GPIO.HIGH:
                    print(
                        f"🚪 {datetime.now().strftime('%H:%M:%S')} 门已关闭，"
                        f"{CLOSE_DELAY_SECONDS} 秒后结算..."
                    )
                    watchdog_timer = time.time()

                if EVENT_ACTIVE and watchdog_timer > 0:
                    if time.time() - watchdog_timer >= CLOSE_DELAY_SECONDS:
                        time.sleep(3)
                        print("\n⏳ 行为结束，正在整理素材...")

                        all_files = sorted(RAM_DIR.glob("*.h264"))
                        if pre_files and pre_files[0] in all_files:
                            start_index = all_files.index(pre_files[0])
                            files_to_merge = all_files[start_index:-1]
                        else:
                            files_to_merge = all_files[:-1]

                        if files_to_merge:
                            event_id = int(time.time())
                            staging_dir = Path(f"/dev/shm/task_{event_id}")
                            staging_dir.mkdir(parents=True, exist_ok=True)

                            for file_path in files_to_merge:
                                shutil.copy(file_path, staging_dir)

                            threading.Thread(
                                target=async_task,
                                args=(staging_dir, event_id),
                                daemon=True,
                            ).start()

                        EVENT_ACTIVE = False
                        watchdog_timer = 0.0
                        print("🚀 重回监控状态。")

            last_state = current_state
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n👋 停止监控...")
    finally:
        camera_process.terminate()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
