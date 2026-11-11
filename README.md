# J716F Ubuntu / Mainline Linux

联想小新 Pad Pro 2021（**TB-J716F，Snapdragon 870，128GB**）的 Linux 移植源码、配置与验证工具。

当前开发版本固定为 **Linux 7.4-rc2 + Ubuntu 26.10 ARM64 / GNOME 51**，验证记录截至 2026-11-11；GitHub 默认分支 `main` 以此版本为当前开发主线。这是开发移植，尚未发布经过全流程验收的通用安装镜像；旧的 Ubuntu 22.04 R3 教程不适用于直接安装当前版本。

## 当前入口

- [构建内核与来源校验](docs/mainline/BUILD.zh-CN.md)
- [硬件状态、已验证内容与限制](docs/mainline/STATUS.zh-CN.md)
- [关键修正与技术说明](docs/mainline/FIXES.zh-CN.md)
- [固件、用户态与再分发边界](docs/mainline/FIRMWARE.zh-CN.md)
- [发布内容与本地验证清单](docs/mainline/PUBLICATION.zh-CN.md)
- [最新运行配置与部署位置](docs/mainline/RUNTIME.zh-CN.md)
- [固定版本、来源和 SHA-256](docs/mainline/sources.json)

已在实机验证显示、触摸、Wi-Fi、扬声器、麦克风、指纹录入/解锁以及 FD650 硬件渲染。启动白线已通过显示时钟接管修正消除；蓝牙适配器和扫描已恢复。具体测试范围及未验证功能以状态文档为准。

随机卡死排查中修正了一段遗漏的 4 MiB 固件预留内存，短时复测通过；目前仍保留定时器规避配置，不能据此承诺长期稳定。整机挂起/恢复、相机和完整电源管理尚未验收。

## 源码布局

```text
patches/kernel/linux-7.4-rc2-j716f.patch   当前 55 文件组合补丁
kernel/linux-7.4-rc2/                    完整、已调试的主线内核源码
configs/kernel/j716f-7.4-rc2.config       已构建的内核配置
configs/ubuntu/                         音频、指纹、充电、USB 网络与桌面配置
configs/initramfs/mainline-*             日常启动、根文件系统接管与独立诊断参考
tools/project/                          固定来源准备、构建与诊断工具
tools/power/                            充电界面与供电检测源码
docs/mainline/                          当前开发文档
```

当前完整内核源码位于 [kernel/linux-7.4-rc2/](kernel/linux-7.4-rc2/)，逐个文件与固定上游加组合补丁重建的源码核对一致，包含已实测的 USB 运行时覆盖层的板级集成；配置同时保存在该目录的 j716f.config 和 configs/kernel 中。精确上游提交、组合补丁及 [源码快照清单](docs/mainline/kernel-source-manifest.json) 保留，便于复现和检查。快照不含额外编译产物；上游原有的图片、测试素材等完整保留。

现有 `kernel/linux-6.15.11/` 保留为旧 #530 版本，不是当前构建目标。若使用稀疏检出，需运行 `git sparse-checkout add kernel/linux-7.4-rc2` 才会在工作区展开新源码。

## 旧版 R3

Ubuntu 22.04 / Linux 6.15.11 #530 的材料保留在 [旧版安装说明](docs/INSTALL.zh-CN.md)、[旧版状态](docs/STATUS.zh-CN.md)及 [R3 元数据](docs/releases/)。这些材料与当前 7.4/26.10 开发版本分开使用。

## 数据与许可

固件、镜像、构建缓存、设备/GPT 备份、录音截图、SSH 密钥、账户密码及个人诊断记录均不纳入此次提交。日常启动已移除无认证 Telnet，只保留 USB 网络供另行配置的 SSH 使用。单独保留的 RAM 诊断工具属于开发用途。

遵循各组件原有许可与 SPDX；详见 [来源和许可](LICENSES/README.md)。当前没有向上游维护者发送补丁，也不以工具身份添加 Signed-off-by。
