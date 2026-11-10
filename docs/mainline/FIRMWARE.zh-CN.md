# 固件、用户态与分发边界

内核源码不等于完整可启动系统。此分支仅提交源代码、配置、补丁和诊断工具，不包含原厂固件、Ubuntu 根文件系统、Chrome、指纹模板或设备备份。

## 固件来源

实机移植参考用户自行提供的 TB-J716F ZUI 12.5.126 原厂包。DSP、Wi-Fi、蓝牙、GPU GMU/ZAP、触摸配置及指纹 TA 等必须来自合法取得且适配本机的来源。不要将原厂包或私有镜像直接提交到仓库。

新内核所需 Adreno SQE 版本高于早期原厂微码。本次使用 Ubuntu 官方 linux-firmware-qualcomm-graphics 包中适用的 a650_sqe.fw；精确摘要和出处见 sources.json。再分发前仍需按相应固件许可证逐项确认。

extract-stock-vendor.py 可离线检查 QPST 原始片段及逻辑分区元数据；不会挂载设备或执行刷写。audit-reserved-memory.py 可读取本地 boot/DTBO 中的静态预留范围。

## Ubuntu 26.10 用户态

使用官方 ARM64 Base 和发行版软件包。桌面为 GNOME/Wayland/PipeWire；音频 UCM、WirePlumber、充电模式、静默输出和稳定性策略参考 configs/ubuntu。

专用 libfprint/QSEE 运行库需要依据 docs/UPSTREAMS.json 的固定上游重建，并应用 Ubuntu 26.10 构建适配补丁。不得复制现有系统的 /var/lib/fprint、账户散列、SSH 主机密钥、个人公钥或私有浏览器配置。

不要直接覆盖发行版的认证链来获得指纹入口；先核对运行库 ABI、服务权限和设备访问，并完成录入、错误手指拒绝、正确手指解锁和重启验证。

## 设备写入与恢复

本机测试曾使用 B 槽，但 B 槽不是自动安全保证。所有分区写入都需要核对机型、分区布局、镜像尺寸及摘要；刷写后需要读回校验。安装 Ubuntu 或回收 Android 分区可能破坏原系统和用户数据。

此分支没有通用的重分区或一键刷机入口。以前绑定单台设备 UUID、容量和旧镜像摘要的在线脚本仅留在开发工作区，不通过删除保护条件的方式改成公共工具。
