# 项目结构

更新日期：2026-11-12。当前 7.4/26.10 主线版本以 [主线构建说明](mainline/BUILD.zh-CN.md) 和 [状态](mainline/STATUS.zh-CN.md) 为入口。旧版 R3 的 6.15.11/22.04 源码与材料同时保留，按下表区分用途。

为保持已有构建脚本可用，大型工作目录留在原位置，Git 只记录整理后的源码入口。

| 目录 | 内容 |
| --- | --- |
| `docs/mainline/` | 当前 7.4/26.10 状态、构建、运行配置与验证记录 |
| `docs/INSTALL.zh-CN.md`、`docs/BUILD.zh-CN.md`、`docs/STATUS.zh-CN.md` | 旧版 R3 安装、构建和状态记录 |
| `docs/releases/` | R3 发布清单、镜像摘要和 ZIP 校验值；没有镜像本体 |
| `kernel/linux-7.4-rc2/` | 当前完整基础内核源码和 j716f.config |
| `kernel/linux-6.15.11/` | 保留的 R3 #530 完整内核源码 |
| `configs/kernel/` | 当前 7.4 配置、旧 #530 配置和独立 ADC 覆盖层 |
| `configs/ubuntu/` | 当前音频、指纹、充电、桌面、USB 网络及系统配置 |
| `configs/audio/`、`configs/fingerprint/` | 保留的旧版音频及指纹配置 |
| `configs/initramfs/` | 当前 mainline 磁盘启动/诊断参考，以及旧版 R3 init |
| `patches/kernel/` | 7.4 与 6.15.11 的组合补丁及各自来源记录 |
| `patches/userspace/` | libfprint J716F 驱动改动 |
| `tools/release/` | R3 镜像导出、清理、合并及相关维护脚本 |
| `tools/project/` | 源码快照和本地仓库检查工具 |
| `tools/input/`、`tools/sensors/` | 输入与传感器运行脚本 |
| `tools/power/` | 充电界面、供电读取、电源键与光感合盖策略 |
| `tools/camera/` | 7.4 独立相机驱动源码、构建/安装及 CMA 启动参数工具 |
| `tools/network/` | 本机固定 Wi-Fi MAC 与旧连接绑定修正 |
| `tools/display-scaling/` | R3 Xorg 缩放修正源码、补丁和构建脚本 |
| `tools/stability/` | 稳定性记录服务与配置 |
| `tools/fingerprint-system/` | 用户态构建入口、服务单元及控制程序源码 |
| `mkbootimg-aosp/` | AOSP 启动镜像工具 |

## 更新来源快照

当前 7.4 源码的重建与快照核对见 [源码快照说明](mainline/KERNEL-SOURCE.zh-CN.md)，独立相机模块另见 [相机说明](mainline/CAMERA.zh-CN.md)。

下面两个入口用于保留的旧版 R3；需有相应源树和原版 tarball：

```sh
python3 tools/project/snapshot-kernel.py
python3 tools/project/snapshot-userspace.py
```

它们只读取构建源树，生成补丁、版本和摘要，不修改内核或嵌套上游仓库。
生成后检查差异，再更新提交。`tools/release` 依赖的私有构建缓存及公开运行库产物没有自动放进 Git。
