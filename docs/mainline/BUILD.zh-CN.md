# 构建固定版本主线内核

建议在 WSL2 的 Linux 文件系统中构建。不要直接把构建目录放在 Windows 挂载盘上；源码准备与编译不需要连接平板，也不执行刷写。

## 依赖与固定来源

Debian/Ubuntu 构建环境可安装：

```sh
sudo apt install build-essential gcc-aarch64-linux-gnu bc bison flex \
  libssl-dev libelf-dev dwarves device-tree-compiler cpio python3 curl git
```

在仓库根目录运行：

```sh
mkdir -p build/downloads
curl --fail --location \
  https://codeload.github.com/torvalds/linux/tar.gz/7475ea8b58616b33c04afb976cf0fbaad9dd63fb \
  --output build/downloads/linux-7.4-rc2.tar.gz
python3 tools/project/prepare-mainline.py \
  --archive build/downloads/linux-7.4-rc2.tar.gz
JOBS=4 bash tools/project/build-mainline.sh
```

prepare-mainline.py 校验上游压缩包、组合补丁和配置的 SHA-256，只向新的目录解压并应用补丁。版本信息见 [sources.json](sources.json)，不是动态跟踪最新主线。

默认输出：

```text
build/mainline/linux-7.4-rc2/arch/arm64/boot/Image
build/mainline/linux-7.4-rc2/arch/arm64/boot/dts/qcom/sm8250-lenovo-j716f.dtb
build/mainline/linux-7.4-rc2/                 模块构建结果
```

完整组合补丁包含当前全部移植改动及 RPMh 超时修正。单独保存的上游 RPMh 补丁仅供来源追踪，不要再次叠加。保留各文件许可，不自行补写人类 Signed-off-by。

## 充电检测与输入恢复自检

以下命令只构建/测试本机程序，不访问平板：

```sh
mkdir -p build/checks
cc -std=c11 -Wall -Wextra -Werror \
  tools/power/test-charge-vbus.c -o build/checks/test-charge-vbus
build/checks/test-charge-vbus
python3 tools/input/test_reprobe_keyboard.py
```

ARM64 充电界面可交叉编译：

```sh
aarch64-linux-gnu-gcc -O2 -static -Wall -Wextra -Werror \
  tools/power/charge-only.c -o build/checks/j716f-charge-only
```

配置参考位于 configs/ubuntu/charge-only；它们是源码材料，不会因编译自动安装到系统。

## 诊断镜像与实际安装的区别

build-verified-diag.py 可接收另行取得、摘要匹配的 R3 boot，替换为 RAM-only init 并移除自动分区合并入口。它需要自己的固件和适配的启动组件，不能仅凭 Image、DTB 两个文件完成安装。

build-mainline-diag.py 是早期布局诊断工具，输出默认标记为未实机验证；不要将其自动视为当前可用启动镜像。无认证 USB Telnet 只应用于受控的本地诊断。

本发布分支不包含绑定某台设备 UUID、原 boot 摘要或个人账户的在线刷写脚本，也没有通用的 Ubuntu 26.10 一键安装器。生成 boot、部署模块与固件、根文件系统首次启动，以及恢复方案仍需独立整理与验收。
