# 当前关键修正

全部内核改动已包含于 linux-7.4-rc2-j716f.patch，相对 sources.json 指定的上游提交，共 53 个文件。以下是问题与验证范围的摘要。

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

## 其他已验证工作

- 双 DSI 的 PHY 偏置状态、实际 byte/pixel/interface 时钟缓存，以及数字顶层 PLL 供电处理。
- 新音频框架下的扬声器与 VA 麦克风路由、GPIO 选择和 UCM 配置。
- Goodix/QSEE 用户态集成及重启后的指纹解锁。
- 缺失键盘输入节点的有限重探测、CJK/终端字体、静默启动。

完整适用范围与尚未验证功能见 [状态说明](STATUS.zh-CN.md)。这些修正不是整机长期稳定性认证。
