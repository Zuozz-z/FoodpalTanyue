# Hardware Setup

## Hall Sensor

The default configuration uses BCM GPIO 26.

| Hall sensor | Raspberry Pi |
|---|---|
| VCC | 3.3V |
| GND | GND |
| Signal | GPIO 26 |

The program configures the signal pin with a pull-down resistor.

## Camera

Confirm that the camera is available:

```bash
rpicam-hello --list-cameras
```

Test recording:

```bash
rpicam-vid -t 5000 -o test.h264
```

## FFmpeg

Confirm installation:

```bash
ffmpeg -version
```

## OSS

Configure `ossutil` before running the program. Keep the configuration file outside the repository and never commit AccessKey credentials.
