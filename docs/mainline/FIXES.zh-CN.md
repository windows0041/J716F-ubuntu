# 当前关键修正

全部内核改动已包含于 linux-7.4-rc2-j716f.patch，相对 sources.json 指定的上游提交，共 56 个文件。以下是问题与验证范围的摘要。

## 固件预留内存

SM8250 默认 removed_mem 为 `0x80b00000 + 0x5300000`（83 MiB），运行时把 `0x85e00000–0x861fffff` 列作普通 System RAM。J716F 板级覆盖改为 `0x5700000`（87 MiB），保留 no-map，结束地址与 camera_mem 的 `0x86200000` 相接；本地原厂 ZUI 12 配置也与此边界一致。

重启后已确认缺少的 4 MiB 被保留。五分钟八核内存模式读写及负载/空闲交替通过，最高 65.5°C。此结果不证明此前所有卡死都只有这一个原因；当前定时器规避仍保留。

## 开机白色横线

原厂 Android 无白线。隔离试验中，跳过 MSM DRM 和 simpledrm 仍出现半屏残留及白线；额外跳过 DISPCC 初始化后，Lenovo 标志完整且无白线。问题发生在 DRM 正式接管之前。

J716F 的 MDP 时钟注册改用现有 `clk_rcg2_shared_no_init_park_ops`，避免注册时把 Bootloader 正在使用的 MDP 时钟切到安全源。仅对 lenovo,j716f 生效，保留后续启停和调频。正常桌面镜像重启后用户确认白线消失、亮度和画面正常；GPU 渲染、像素读回和空闲恢复也通过。

## 面板电源控制

原厂用 GPIO60 作显示使能、GPIO61 控制 AVDD。原移植遗漏前者，后者误写为 fixed-regulator 不读取的 enable-gpios。现补齐可选面板使能，并使用 gpio 与 enable-active-high 描述 AVDD。两根引脚在实机被内核接管；该项本身没有消除白线，不与时钟修正混淆。

## 充电进入桌面后蓝牙不可用

BlueZ 在充电模式启动正常，但进入桌面的 isolate graphical.target 操作会停止未列入桌面依赖的 Bluetooth target。新增 graphical.target 的 Wants=bluetooth.target，恢复服务后控制器 Powered=yes，用户确认开关与扫描正常。修正后的完整物理充电→桌面流程尚待再次验证。

## USB-C 角色与高速通道

板级 DTS 启用 PM8150B Type-C/VBUS，将 DWC3、连接器、QMP PHY 和 NB7VPQ904M 连接起来。当前禁用 PD 协商，优先受电，DWC3 使用 OTG 角色切换；主机与快充功能尚待外设验证。

NB7VPQ904M 原驱动只注册 retimer，普通 USB 的 mode-switch 事件没有到达该芯片。增加可选 mux 注册并共用模式设置路径，使 USB 模式与插头方向共同决定通道；保留原有 retimer 接口，并补齐 clientdata 与释放路径。实机正反插能恢复网络，芯片通道状态随方向变化。现有连接仅协商到 480 Mbps，同线、同电脑连接对照手机也为 480 Mbps，尚不能宣称 USB 3.x 已实测通过。

曾强制 `maximum-speed = "super-speed"` 导致当前 SM8250 映射范围外的寄存器访问；现保留控制器自动协商，没有修改 DWC3 核心或宣称解决全部高速链路问题。

## 日常启动与重启

清理后的磁盘 initramfs 保留 RNDIS/ECM 描述符、根文件系统身份及内核摘要检查、离线 fsck 和失败恢复入口，移除 Telnet、早期 DHCP 和常驻启动日志。USB 地址与 DHCP 由 Ubuntu 的专用网络服务设置，日常远程登录使用另行配置的 SSH。

systemd 的重启看门狗在该平台产生超时不支持及无法停止的屏幕提示。运行配置设为 `RebootWatchdogSec=off` 后，用户确认重启无提示、正常进入桌面。这只关闭重启阶段的看门狗接管，不禁用驱动或改写内核错误日志。

## 其他已验证工作

- 双 DSI 的 PHY 偏置状态、实际 byte/pixel/interface 时钟缓存，以及数字顶层 PLL 供电处理。
- 新音频框架下的扬声器与 VA 麦克风路由、GPIO 选择和 UCM 配置。
- Goodix/QSEE 用户态集成及重启后的指纹解锁。
- 缺失键盘输入节点的有限重探测、CJK/终端字体、静默启动。

完整适用范围与尚未验证功能见 [状态说明](STATUS.zh-CN.md)。这些修正不是整机长期稳定性认证。

## 满电拔线后仍显示充电

实测 VBUS 为 0 V、Type-C online 为 0、电池电流为负，但电量 99% 时 gauge 的 FC 标志仍置位，内核和 UPower 因而继续报告 Full，桌面未切换到电池供电。电量降到 98% 后自行恢复。TI 对 BQ27541 的 [FC 清除阈值说明](https://www.ti.com.cn/cn/lit/an/slua561b/slua561b.pdf) 也描述了这种满电标志滞后。

仅在 lenovo,j716f 上，先判断负电流并报告 Discharging，再处理满电标志，其他平台保留原优先级。不修改电池数据闪存、充电阈值或硬件控制寄存器。测试直接提取驱动函数，覆盖满电标志与负电流共存、正电流、零电流、非 J716F 行为及读取错误，共 9 个用例。完整 Image 增量构建通过，模块符号表未变；既有 DTB、命令行、固件及普通启动配置保持原样。

新内核 B 槽读回摘要已核对，重启后用户确认拔线显示电池供电；重新接线时电流为正并报告 Charging。满电标志与负电流共存的判定由前述驱动函数回归用例覆盖。
