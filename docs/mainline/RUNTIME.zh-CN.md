# 日常运行配置

这些文件对应当前已实测安装的通用配置。不会因检出仓库自动安装，也不替代完整的初次安装流程。部署前需确认版本、设备布局和现有服务；设备 UUID、账户、密钥及固件均需自行准备。

## USB 网络

| 仓库文件（configs/ubuntu/usb-network/ 下） | 安装位置 |
| --- | --- |
| j716f-usb-network | /usr/local/sbin/j716f-usb-network，0755 |
| j716f-usb-network.service | /etc/systemd/system/j716f-usb-network.service |
| j716f-usb-udhcpd.conf | /etc/j716f-usb-udhcpd.conf |
| 90-j716f-usb-network.conf | /etc/NetworkManager/conf.d/90-j716f-usb-network.conf |

服务依赖 `iproute2` 和 `/usr/bin/busybox-static` 的 udhcpd，识别固定的 USB gadget MAC，设置平板 `172.16.30.1/25`，仅向电脑分配 `172.16.30.2/25`，不提供网关或 DNS。部署后执行 `systemctl daemon-reload`、`systemctl enable j716f-usb-network.service`。不要同时运行旧 `j716f-usb-diagnostics.service`；充电 target 已改为引用网络服务。

日常 initramfs 使用 `configs/initramfs/mainline-disk-init` 和 `mainline-mount-disk-root`，不包含 Telnet。SSH 由根文件系统的 OpenSSH 单独提供，账户及认证配置不随源码分发。USB gadget 内部路径及固定字符串保留历史命名，避免改变 Windows 已绑定的设备身份。RAM 诊断目录下的 Telnet 参考与日常配置分开使用。

根文件系统接管仍需在 initramfs 中提供当前设备的 UUID、允许容量及实际内核 SHA-256 文件；`/boot/Image-7.4.0-rc2-j716f` 必须指向匹配的内核。失败时留在本地控制台恢复环境，不开启网络 shell。默认静默，可显式添加 `j716f.boot_verbose=1` 查看早期输出。

## 重启与软件源

`configs/ubuntu/90-j716f-watchdog.conf` 对应 `/etc/systemd/system.conf.d/90-j716f-watchdog.conf`，关闭本机不适用的重启看门狗接管。修改此类 Manager 配置需正常重启或按 systemd 文档重载管理器；本机已经重启验证。

`configs/ubuntu/apt/ubuntu.sources` 对应 Ubuntu 26.10 ARM64 的 `/etc/apt/sources.list.d/ubuntu.sources`，使用中科大 `ubuntu-ports`，保留原 Ubuntu 签名密钥。仅适用于 `stonking`，替换时避免保留重复的官方 Ubuntu 条目，然后运行 `apt update`。本机更新已通过。

按用户要求，当前安装的 Google APT 条目已改为 `.sources.disabled`，暂不参与更新；源码仓库不分发第三方浏览器包或个人浏览器设置。

清理只移除了安装中的旧诊断服务、实验脚本、已备份的旧镜像和缓存；所需固件、匹配模块、fsck、指纹及音频组件继续保留。用户已确认清理后重启、桌面、键盘和触控板正常。
