# Ubuntu on Lenovo TB-J716F

联想小新 Pad Pro 2021（TB-J716F，128GB）的 Ubuntu 22.04 ARM64 移植项目。
当前内核 **Linux 6.15.11 #530**，干净安装包修订版 **R3**。

本仓库保存移植源码改动、配置和打包流程。完整镜像、原厂固件、构建缓存、设备备份及个人数据留在本地，不进入 Git。

## 使用与状态

- [刷机教程](docs/INSTALL.zh-CN.md)：从已解锁的设备安装 Ubuntu，支持安装时合并 super 与 userdata。
- [硬件状态与验证范围](docs/STATUS.zh-CN.md)
- [构建说明](docs/BUILD.zh-CN.md)
- [项目目录与维护方式](docs/PROJECT-LAYOUT.zh-CN.md)
- [本地仓库及数据边界](docs/REPOSITORY.zh-CN.md)
- [第三方来源与许可](LICENSES/README.md)

R3 修正了新账户未启用音频服务、指纹运行库漏包的问题，并移除 Speaker Test 应用；四扬声器运行配置保留。
用户已确认当前设备声音和指纹正常。本轮修正没有再次刷写设备。

## 安装包

本机文件：`releases/j716f-ubuntu-22.04-clean-530-r3.zip`。
SHA-256：`02cd21443ee5d8e8a567ff65ec4863c3987611daee8da516e0d7b6df8344af83`。
发布元数据及校验值保存在 [docs/releases/](docs/releases/)，镜像本体不在 Git 中。

安装会清空目标系统和个人数据。原厂布局会合并 super 与 userdata，合并后约 116.25 GiB；已经合并的布局跳过重复操作。
适用机型、分区检查和全部步骤以教程为准。

## 验证范围

用户已确认按 R1 教程刷入并进入 Ubuntu，声音和指纹随后在线修正并确认正常。
R3 完成文件系统、稀疏镜像、关键依赖和归档完整性核对；R3 整包再次擦除安装以及从原厂未合并布局开始的完整流程尚未实机验收。

## 开发入口

```text
configs/                 内核、音频、触控、指纹与 initramfs 配置
patches/kernel/          相对原版 Linux 6.15.11 的 #530 完整源码补丁
patches/userspace/       相对固定上游提交的用户态改动
mkbootimg-aosp/          AOSP Android 启动镜像工具
tools/release/          干净镜像导出、初始化、修正和 fastboot 安装脚本
tools/project/          本地仓库整理与源码快照工具
```

上游精确提交见 [docs/UPSTREAMS.json](docs/UPSTREAMS.json)。
当前仅创建本地 Git 仓库，没有配置远端或上传到 GitHub。
