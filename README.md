# Foomie Hardware Video Collector

Foomie 硬件端视频采集与云端上传程序。

本仓库负责完成从 **冰箱门状态检测 → 视频持续采集 → 事件片段整理 → 阿里云 OSS 上传 → 云端分析** 的完整硬件数据链路，为后续 AI 视频分析提供输入。

> 当前仓库只包含硬件端采集与上传代码，不包含云端 AI 分析代码。

## 已实现功能

- 使用 Raspberry Pi 摄像头持续录制视频
- 用户打开冰箱门开始侦测，每 10 秒生成一个 H.264 视频切片
- 使用内存盘暂存视频，降低存储写入压力，保留事件发生前的预录片段
- 将 MP4 上传至阿里云 OSS
- 生成临时签名预览链接
- 上传完成后自动清理本地临时文件
- 内存守护线程自动删除过旧切片

## 系统流程

```text
硬件检测到冰箱门开启
          ↓
Raspberry Pi 摄像头持续录制
          ↓
H.264 视频切片写入 /dev/shm
          ↓
门开启：开始记录事件
          ↓
门关闭并等待 10 秒
          ↓
复制相关切片至临时任务目录
          ↓
FFmpeg 合并为 MP4
          ↓
上传至阿里云 OSS
          ↓
生成临时预览链接
```

## 仓库结构

```text
foomie-hardware-collector/
├── main.py                 # 建议公开使用的参数化版本
├── main_original.py        # 原始硬件代码备份
├── .env.example            # 配置示例
├── .gitignore
├── requirements.txt
├── LICENSE
└── docs/
    └── hardware-setup.md
```

## 硬件与系统要求

- Raspberry Pi
- Raspberry Pi Camera
- 霍尔传感器
- Raspberry Pi OS
- Python 3.10+
- `rpicam-vid`
- `ffmpeg`
- 阿里云 `ossutil`

## 安装

### 1. 克隆仓库

```bash
git clone https://github.com/YOUR_NAME/foomie-hardware-collector.git
cd foomie-hardware-collector
```

### 2. 安装 Python 依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 安装系统依赖

```bash
sudo apt update
sudo apt install -y ffmpeg python3-rpi.gpio
```

请根据阿里云官方说明安装并配置 `ossutil`。

## 配置

复制配置示例：

```bash
cp .env.example .env
```

加载环境变量：

```bash
set -a
source .env
set +a
```

主要参数：

| 参数 | 说明 | 默认值 |
|---|---|---|
| `FOOMIE_USER_ID` | 用户或设备标识 | `user4` |
| `FOOMIE_HALL_PIN` | 霍尔传感器 GPIO BCM 编号 | `26` |
| `FOOMIE_RAM_DIR` | 内存盘视频目录 | `/dev/shm/live_videos` |
| `FOOMIE_OSS_DEST` | OSS 上传根路径 | 示例 Bucket 路径 |
| `FOOMIE_OSS_CONFIG` | ossutil 配置文件 | `/home/<user>/.ossutilconfig` |
| `FOOMIE_MAX_FILES` | 空闲时最多保留的切片数量 | `5` |
| `FOOMIE_SEGMENT_MS` | 单个视频切片时长 | `10000` |
| `FOOMIE_CLOSE_DELAY_SECONDS` | 门关闭后的结算等待时间 | `10` |

## 运行

```bash
python3 main.py
```

正常启动后会显示：

```text
🚀 [Foomie Hardware Collector 就绪] 监控中...
```

当冰箱门开启、关闭并完成上传后，终端会输出上传状态与临时预览链接。

## OSS 文件结构

```text
uploads/
└── <user_id>/
    └── event_<timestamp>/
        └── event_<timestamp>.mp4
```

## 当前边界

本仓库当前不包含：

- 云端视频分析服务
- 食物识别
- 进食动作识别
- 营养计算
- 用户报告生成

这些能力属于后续分析系统，不应在本仓库中标记为已完成。

## 安全说明

- 不要提交 `.env`
- 不要提交 `.ossutilconfig`
- 不要在代码中写入 AccessKey
- 不要公开包含真实用户隐私的视频
- 演示视频建议使用测试数据或获得授权的数据

## License

MIT License
