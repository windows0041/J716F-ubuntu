# 构建固定版本主线内核

建议在 WSL2 的 Linux 文件系统中构建。不要直接把构建目录放在 Windows 挂载盘上；源码准备与编译不需要连接平板，也不执行刷写。

## 依赖

Debian/Ubuntu 构建环境可安装：

```sh
sudo apt install build-essential gcc-aarch64-linux-gnu bc bison flex \
  libssl-dev libelf-dev dwarves device-tree-compiler cpio python3 curl git
```

## 直接构建已调试的完整源码

仓库已包含 kernel/linux-7.4-rc2，可直接在仓库根目录运行，不必先下载上游归档：

```sh
mkdir -p build/kernel-7.4-rc2
cp kernel/linux-7.4-rc2/j716f.config build/kernel-7.4-rc2/.config
make -C kernel/linux-7.4-rc2 O="$PWD/build/kernel-7.4-rc2" \
  ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- olddefconfig
make -C kernel/linux-7.4-rc2 O="$PWD/build/kernel-7.4-rc2" \
  ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j4 \
  Image modules qcom/sm8250-lenovo-j716f.dtb
```

配置使用普通文件名 j716f.config 保存，避免源码目录中的 .config 阻止 Kbuild 的 O= 分离构建。构建结果位于 build/kernel-7.4-rc2，源码树保持干净。它与 configs/kernel/j716f-7.4-rc2.config 的字节和摘要一致。

## 从固定上游重建相同源码

也可在仓库根目录运行原有的归档准备流程：

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

该归档准备流程的默认输出：

```text
build/mainline/linux-7.4-rc2/arch/arm64/boot/Image
build/mainline/linux-7.4-rc2/arch/arm64/boot/dts/qcom/sm8250-lenovo-j716f.dtb
build/mainline/linux-7.4-rc2/                 模块构建结果
```

完整组合补丁包含当前全部移植改动及 RPMh 超时修正。单独保存的上游 RPMh 补丁仅供来源追踪，不要再次叠加。保留各文件许可，不自行补写人类 Signed-off-by。

完整源码的导出方法与一致性记录见 [源码快照说明](KERNEL-SOURCE.zh-CN.md)。源码一致不等于任意构建环境会生成字节完全相同的 Image；编译器、时间戳等也会影响构建摘要。

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

## USB 模块与运行配置

NB7VPQ904M 配置为模块，构建结果为 `drivers/usb/typec/mux/nb7vpq904m.ko`。日常 initramfs 在 USB 枚举前从 `/bin/nb7vpq904m.ko` 加载它；打包时必须包含与同一内核配置及符号版本匹配的模块，根文件系统也应部署完整匹配的模块目录。USB-C 角色及 redriver 拓扑已合并到板级 DTS，不要重复叠加早期 USB 测试覆盖层，也不要强制设置 `maximum-speed = "super-speed"`。

充电电压 ADC 的独立覆盖层仍在 `configs/kernel/j716f-usbin-adc-overlay.dts`，组装完整启动镜像时需要保留。运行服务、国内 APT 源及日常启动配置见 [运行配置](RUNTIME.zh-CN.md)。

## 诊断镜像与实际安装的区别

build-verified-diag.py 可接收另行取得、摘要匹配的 R3 boot，替换为 RAM-only init 并移除自动分区合并入口。它需要自己的固件和适配的启动组件，不能仅凭 Image、DTB 两个文件完成安装。

build-mainline-diag.py 是早期布局诊断工具，输出默认标记为未实机验证；不要将其自动视为当前可用启动镜像。无认证 USB Telnet 只应用于受控的本地诊断。

当前 `main` 分支不包含绑定某台设备 UUID、原 boot 摘要或个人账户的在线刷写脚本，也没有通用的 Ubuntu 26.10 一键安装器。生成 boot、部署模块与固件、根文件系统首次启动，以及恢复方案仍需独立整理与验收。
