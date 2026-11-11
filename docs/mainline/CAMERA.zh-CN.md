# 7.4 相机接入

2026-11-12 实机验证：Ubuntu 26.10 的 GNOME 相机（Snapshot）能切换三个
RGB 摄像头并保存照片。前摄 S5K4H7、后摄 GC5035 已由用户确认；OV13B10
先因连续内存不足导致应用退出，扩容并重启后用户确认预览和拍照正常。
驱动开机自动加载，正常重启后已检查三路均可枚举。

## 驱动与构建

本阶段将传感器作为独立模块安装，基础内核 Image、DTB 和 initramfs 未改。
完整基础内核仍在 `kernel/linux-7.4-rc2`，新增驱动在 `tools/camera/modules`：

* OV13B10：复用 7.4 原生驱动，增加设备树匹配表。
* GC5035：保留 R3 驱动和原作者许可，适配 7.4 subdev 回调。
* S5K4H7：移植 R3 驱动；固定实际全幅格式，补上曝光、增益、水平/垂直
  消隐控制，修正运行时电源与移除清理，提供裁剪区域查询。
* V4L2 CCI：复用同一 7.4 基础树的辅助模块。

旧包的 `530` 是构建编号，其内核为 6.15.11，不是 Linux 5.3.0。
当前使用 19.2 MHz MCLK 和已实测的寄存器序列，不切换相机时钟源。

先按主线构建说明构建准确匹配的基础内核，保留 `.config`、`Module.symvers`、
生成头文件和 `arch/arm64/boot/Image`，然后在 Linux 执行：

```sh
sh tools/camera/build-modules.sh /absolute/kernel-build-tree /absolute/new-camera-output
```

使用 `O=` 分离构建时，第三个参数必须传源码目录，例如
`sh tools/camera/build-modules.sh "$PWD/build/kernel-7.4-rc2" "$PWD/build/camera" "$PWD/kernel/linux-7.4-rc2"`。

脚本核对复用驱动的源码摘要并生成模块与清单。此入口针对当前基础配置：
`CONFIG_VIDEO_QCOM_CAMSS=y`，基础内核没有启用 `CONFIG_V4L2_CCI_I2C`。
编译输出包含 `.ko` 与 `manifest.json`，不进入 Git。

将输出复制到平板，在相同内核版本下执行：

```sh
sudo python3 tools/camera/install-modules.py /path/to/camera-output
sudo apt install v4l-utils libcamera-tools libcamera-ipa gstreamer1.0-libcamera \
    libspa-0.2-libcamera gnome-snapshot
```

安装程序核对内核版本、`/boot/Image` 和模块 SHA256，保存已有模块备份，
安装至 `updates/j716f-camera`，运行 depmod 并设置开机加载。不会在线卸载
正在使用的相机驱动。修改基础内核后必须重新编译，不要只复制旧模块。

## 连续图像内存

基础配置只有 32 MiB 默认 CMA。OV13B10 的 1080p XRGB8888 每帧为
8,294,400 字节，申请多缓冲时实测出现 `dma-heap allocation failure`。
现在的启动镜像增加 `cma=256M`；加上独立的 8 MiB DSP 区域，
`/proc/meminfo` 中 `CmaTotal` 为 270336 kB。

可在电脑针对已校验、无签名尾部的 Android v2 启动镜像生成修改版：

```sh
python3 tools/camera/set-boot-cma.py source-boot.img new-boot.img
```

此工具只修改命令行，校验其余头部字段及全部 payload 不变，不写平板。
按项目已有的备份、B 槽写入和读回校验流程安装后正常重启。
当前实机的原 B 槽备份保留在平板 `/var/lib/j716f-recovery/camera-cma-20261112/`。

## 验证范围与后续调校

前后主摄分别通过 300 帧 640×480 处理后取帧；扩大 CMA 后 OV13B10
通过 90 帧 1920×1080 输出，约 59.6 fps，并实际保存 JPEG。
GNOME 相机通过 PipeWire/libcamera 工作，驱动输出的是 Bayer 原始图像，
不应直接把 `/dev/video0` 当成 USB 摄像头使用。

最后又按 GC5035 → OV13B10 → S5K4H7 的顺序完成三轮 1080p 切换测试，
每路每轮 240 帧，共 2160 帧；九次取帧均成功，没有新增内核日志或分配失败。

目前使用通用软件 ISP 和自动曝光。缺少本机专用色彩/噪声标定，暗处画质、
自动对焦、视频录像、完整分辨率照片和休眠后的相机恢复仍未全面验收。
S5K4H7 的链路/像素率控制仍继承旧驱动值，实际全幅帧率约 24 fps，
曝光时间元数据应在校准实际 PLL 时序后再作为精确测量使用。
IR 摄像头未启用。本轮未再次复现整机卡死，不能据此宣称长期稳定性已验收。

这些适配由 Codex 根据旧 R3 源码、7.4 API 和实机日志完成，属于功能接入与
电源管理修正；未发现或声称安全漏洞。两个移植驱动通过 checkpatch
（0 error、0 warning），全部模块重新构建无编译告警。未向上游发送补丁，
也未由工具添加 Signed-off-by；上游提交前仍需人工审核来源、许可和 DCO。
