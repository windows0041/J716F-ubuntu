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

## 屏幕键盘、手动休眠与电源键

GNOME 自带屏幕键盘，无需额外安装键盘程序。`configs/ubuntu/dconf/30-j716f-tablet-controls` 启用屏幕键盘与立即锁屏；对应已安装用户也需要设置同名 GSettings 键。保持原来的自动整机休眠关闭策略，手动休眠单独验证。

将 `tools/power/power-key.py` 安装为 `/usr/local/sbin/j716f-power-key`（0755），服务文件位于 `configs/ubuntu/power-key/j716f-power-key.service`，部署到 `/etc/systemd/system/`，然后重新加载并启用服务。依赖 Python 3、PyGObject/Gio、gdbus、runuser 与 systemd。服务只随 graphical.target 运行，与只充电界面的按键处理分开。

| 当前状态与操作 | 行为 |
| --- | --- |
| 亮屏，按住至少 1 秒后松开（例如 1～2 秒） | 锁屏成功后请求系统 suspend |
| 持续按住约 4.5 秒 | 请求正常关机，不调用强制断电 |
| 黑屏或系统休眠，短按一下 | 唤醒显示，保留锁屏认证 |

按住期间不会在第 1 秒先休眠，因此仍可继续按到关机阈值。程序只独占 PMIC 电源键，不独占磁吸键盘或触控板；使用内核单调时钟事件时间，并先处理已排队的松开事件，避免桌面调用延迟把短按误判成长按。

当前内核提供 s2idle。已完成一次 RTC 自动唤醒和一次实体电源键休眠/唤醒，当轮成功计数为 2、失败计数为 0，用户确认唤醒进入锁屏。用户也已验证长按正常关机、重新开机进入桌面及屏幕键盘弹出。此结果不代表长时间睡眠、电池功耗或所有外设的恢复均已验收。只在最初验证时设置了 30 秒 RTC 回退闹钟，日常休眠不设置定时唤醒。

时序测试入口为 `python3 tools/power/test-power-key.py`，不会访问电源键或执行关机。默认不记录按下/松开调试日志；临时环境变量 `J716F_POWER_KEY_TRACE=1` 仅供现场诊断。

## 环境光合盖休眠

此功能用环境光变化推断合盖，不是硬件 Hall 开关。开盖光照至少 20 lux 持续 4 秒后才就绪；5 秒内下降到不超过 3 lux、且不超过此前光照的 10%，再持续 4 秒，才锁屏并请求 s2idle。短暂遮挡、缓慢变暗、传感器失联或启动时已处于暗处均不触发。恢复后有 20 秒保护期，并需重新获得开盖亮度基线，避免盖子仍关着时反复挂起。突然关灯仍可能被误认为合盖，暗处请使用电源键休眠。

策略文件 `tools/power/als-lid.py` 安装为 `/usr/local/sbin/j716f-als-lid`（0755）；`configs/ubuntu/power-key/j716f-als-lid.json` 安装为 `/etc/j716f-als-lid.json`，同目录服务文件安装到 `/etc/systemd/system/`。它复用电源键脚本的本地会话锁屏检查：login1 已报告 LockedHint 时直接请求休眠，避免在锁屏页重复调用 GNOME Lock 导致超时。服务只用于图形桌面，与只充电模式互斥，不调整 GNOME 按空闲时间自动休眠的策略。

光感后端使用 SLPI 固件、SSC 和 reverse FastRPC。当前实机安装 `libssc-bin`/`gir1.2-ssc-2` 0.4.4-2、qrtr-tools，以及来自用户已验证 R3 的 patched hexagonrpcd 和带 SSC 的 iio-sensor-proxy；后者通过系统的新版 libssc 运行。Ubuntu 原生 iio-sensor-proxy 未带 SSC，原生 hexagonrpcd 0.4.0 对所需 registry 写入的限制也不能直接替代本机 patched 版本。

后端可执行文件及 `start-slpi.py`、`wait-light.py`、`ssc-discover.py`、`sensor-sleep.sh` 位于 `/opt/j716f-sensors/libexec/`。固件、R3 二进制、设备 registry 和校准数据不随仓库发布；registry 使用 `/var/lib/j716f-sensors/root` 下的 Linux 私有副本（目录 0700、文件 0600），socinfo 必须匹配实际设备，不写入 Android persist。已验证 hexagonrpcd 的 SHA-256 为 `30be6b3d15d65541dbc417df3ac0d007e49b030271ff4bcd07549f0461f175e6`；源码适配参考 `tools/sensors/patches/`，并非已经验证的新系统从零构建安装流程。

后端 unit 和 udev 规则参考 `tools/sensors/`。将 `configs/ubuntu/sensors/iio-sensor-proxy-ssc.conf` 放入 `/etc/systemd/system/iio-sensor-proxy.service.d/`，`sensor-rpc.conf` 放入 `/etc/systemd/system/j716f-sensor-rpc.service.d/`。不要同时运行发行版 hexagonrpcd 与私有 patched 服务。sleep hook 在挂起前停止 FastRPC 及依赖它的 IIO 服务，恢复时重新启动，避免冻结用户态时阻塞 DSP 调用。qrtr-ns、`j716f-sensor-rpc.service`、`j716f-sensor-sleep.service` 和 `j716f-als-lid.service` 需启用；IIO 服务由依赖关系拉起。

运行状态保存在 `/run/j716f-als-lid/status.json`，只记录亮度、判定状态、请求次数和恢复次数。日志只记录动作与错误，不持续打印光感采样。暂停此功能可执行 `sudo systemctl disable --now j716f-als-lid.service`，电源键处理仍可继续使用。

真实开合盖采样回放识别了一次合盖；实机在桌面和锁屏页均记录到 suspend entry/exit，锁屏测试中一次周期约 69 秒，失败计数未增加。用户观察到合盖黑屏、开盖立即亮屏；测试 RTC 回退闹钟已移除，当前没有自动唤醒定时器。开盖唤醒的具体硬件中断尚未确定，不将其归因于休眠期间已停用的光感用户态服务。16 项光感判定/动作测试和 13 项电源键/锁屏测试通过；正常重启后服务自动运行、光感有有效读数且判定已就绪。不代表长时间待机功耗已经验收。

## 读取充电数据

`tools/power/charge-power.py` 安装为 `/usr/local/bin/j716f-power`（0755）。普通用户运行 `j716f-power` 可读电量、电池电压/电流、相乘得到的电池侧净功率，以及 PMIC ADC5 的 USB 实测电压。`watch -n 1 j716f-power` 每秒刷新，按 Ctrl+C 退出。

电池 sysfs 的 voltage_now 和 current_now 分别以微伏、微安提供，乘积除以 10¹² 得到瓦；正数为净充入，负数为放出。USB ADC 的 usbin_v_input 也是微伏。TCPM 的 current_now 来自角色协商电流限额，不能当作实际输入电流；当前无法据此计算充电器端总输入功率。

## Chrome 启动时的密钥环密码

当前用户明确选择仅让 Chrome 使用本地密码存储，接受其保存凭据不再由系统登录密钥环保护。`configs/ubuntu/desktop/j716f-chrome` 对应可执行的 `/usr/local/bin/j716f-chrome`；该用户的 Chrome desktop 文件中，主入口、新窗口和无痕窗口的 Exec 均改为调用此包装器，保留 Wayland 参数。

这是可选的个人配置，不自动施加给其他用户；不修改账户密码，不清空登录密钥环。原 desktop 文件另行备份，设置过程未改写浏览器配置目录；实测 Chrome 主进程带有 `--password-store=basic`，同时登录密钥环仍锁定。重新开机后，用户再次从图标打开 Chrome，确认没有密钥环密码提示。

## Wi-Fi 自动连接与密钥环

Chrome 的本地密码存储不会改写系统 Wi-Fi 凭据。本机一次启动时，NetworkManager 日志显示缺少认证信息；用户重新连接后，密码才写入 Netplan 永久配置。已重新持久保存活动配置，启用自动连接，设置 PSK 由 NetworkManager 管理（psk-flags=0），并验证保存密码的文件权限为 0600。

Ubuntu 使用 Netplan 后端时，活动连接的文件出现在 /run/NetworkManager/system-connections 本身不表示密码已丢失；应同时检查 /etc/netplan 的持久配置。保存密码后重新生成 Netplan 配置、重启 NetworkManager 和 wpa_supplicant，实测无需新密码请求即可自动连接；此时登录密钥环仍处于锁定状态。现场 Wi-Fi 凭据、网络名及原配置备份不纳入仓库。
