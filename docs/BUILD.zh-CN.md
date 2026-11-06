# 构建与来源说明

## 当前保存范围

已保存最终内核源树相对原版 Linux 6.15.11 的完整源码改动、#530 配置、专用 libfprint 驱动改动及上游固定提交。
大型源树、编译结果、交叉工具链、固件、ARM64 sysroot 和 Ubuntu 导出树保留在原工作区，不纳入 Git。

R3 完整镜像构建仍依赖这些本地输入；当前没有从空白主机一键重建整个 R3 ZIP 的流程。
此次整理没有运行编译、项目测试或设备操作。

## Linux 6.15.11

The complete #530 source tree and configuration are available in `kernel/linux-6.15.11/`. The archive-and-patch method below can reproduce a clean copy.

原版源归档：`linux-6.15.11.tar.xz`，来源为 kernel.org 对应版本。
精确摘要见 `patches/kernel/snapshot.json`。本机缓存位于 `kernel/dl/`。
需要 Python 3、patch、make、ARM64 GCC 交叉编译器及内核构建依赖。

准备新的源树，不覆盖现有开发目录：

```sh
python3 tools/project/prepare-kernel.py \
  --archive /保存位置/linux-6.15.11.tar.xz \
  --dest build/kernel-6.15.11-source
```

需要编译时再显式运行：

```sh
CROSS_COMPILE=aarch64-linux-gnu- bash tools/project/build-kernel.sh
```

`configs/kernel/j716f-6.15.11.config` 是已使用的 #530 配置。
源补丁包含当前源树的触控、QSEE、输入唤醒、DSI、音频及其他已有移植改动；实验性相机/探测代码也随源树保留，不表示相机已经验收。
编译器、构建身份和时间改变会使生成文件摘要不同；新的构建不能被当成原发布二进制的逐字节复制。

## libfprint 与 QSEE

来源与固定提交见 `docs/UPSTREAMS.json`。上游克隆目录保持 Git 忽略，改动以补丁保存。
在新克隆的本项目中，可准备对应目录：

```sh
git clone https://github.com/wrobelda/libfprint.git tools/libfprint-goodix-qsee
git -C tools/libfprint-goodix-qsee checkout 430e24e538ba137b6edcfe2e1b3b8cc29c66fa6a
git -C tools/libfprint-goodix-qsee apply ../../patches/userspace/libfprint-goodix-qsee.patch

git clone https://github.com/wrobelda/qsee-supplicant.git tools/qsee-supplicant
git -C tools/qsee-supplicant checkout 36e06680cf7f690fccbdcd07abc2a64c4bb061d8
```

已有这些目录时不要再次 clone。`tools/fingerprint-system/build-libfprint.sh` 记录本机 Meson/交叉 sysroot 的构建入口；需要先准备脚本引用的构建依赖。
该脚本只构建运行库；早期从单台设备导入旧指纹定位记录的辅助程序保留在本地历史中，不参与干净系统构建。
PAM 运行模块取自 Ubuntu 官方 ARM64 libpam-fprintd 包，不复制其他设备的指纹模板或账户元数据。

## R3 干净镜像

主要入口位于 `tools/release/`：

1. `export-clean-system.py` 只读导出筛选后的系统文件，导出前排除个人资料和认证状态。
2. `sanitize-root.py` 在 fakeroot 下生成干净账户、系统默认项及音频/指纹修正。
3. `make-clean-rootfs.py` 生成 ext4 与 Android sparse 镜像，并核对还原内容。
4. `build-merge-helper.py`、`pack-clean-boot.py` 保留 #530 内核和 DTB，为新根文件系统制作启动镜像。
5. `audit-clean-image.py`、`assemble-package.py`、`archive-package.py` 核对关键文件并制作安装包。

这组脚本会读取未纳入 Git 的原 #530 镜像、工具链/sysroot、公开运行库产物和导出树。路径由 `release_config.py` 及各脚本定义。
开始重新制作前，应先备份现有产物并核对输入；不要删除脚本内的目标型号、容量和摘要保护来强行绕过缺失文件。

发布二进制和摘要见 `docs/releases/`。完整安装步骤见 `docs/INSTALL.zh-CN.md`。
