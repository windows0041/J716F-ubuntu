# Lenovo TB-J716F：Android → 干净 Ubuntu 刷机教程

版本：2026.10.24-clean-530-r3；Ubuntu 22.04 ARM64，Linux 6.15.11 #530。

R2 修正：为新账户启用 PulseAudio 服务及 socket，解决干净安装后完全无声；移除
Speaker Test 测试程序及菜单入口，保留独立的四扬声器开机配置。已安装 R1 的这台平板
已在线修正，并由用户确认 80% 音量下左右声道正常，无需再次清空重刷。

R3 继续补齐专用 libfprint 及 GDM 指纹 PAM 运行库，解决设置不显示指纹选项的问题。
当前设备已在线识别到指纹设备，用户确认设置入口出现、指纹功能正常。
镜像不包含任何旧指纹，安装后需要用户重新录入。

## 1. 适用范围与验证范围

- 机型：联想小新 Pad Pro 2021 **TB-J716F，128GB**，骁龙 870。
- 要求：Bootloader 已解锁，保留该型号正常的原厂底层固件和 A/B 分区布局。
- 支持原厂 userdata 分区大小 116237611008 字节，也支持本项目合并后的
  124827545600 字节；原厂 super 必须为 8589934592 字节。其他尺寸停止安装。
- **原厂布局会在安装时自动合并 super 与 userdata，回收 8 GiB 空间。**
  已合并的设备直接重装，不重复调整分区表。
- 不适用于名称相似的其他平板；256GB 版本及不同底层固件组合未验证。

本包以已经在这台平板运行的 #530 系统组件制作，保留已完成的触控、键盘/触控板、
键盘唤醒、Wi-Fi、蓝牙、麦克风、亮度、环境光、指纹支持、四扬声器及 150% 缩放修复。
个人文件、原用户、Wi-Fi 密码、蓝牙配对、指纹库、浏览器资料及日志均未放入镜像。

**验证范围：** 已检查镜像格式、文件系统、关键文件权限及稀疏镜像还原一致性。
分区合并程序已使用 ARM64 二进制及电脑上的 GPT 副本核对变更范围、CRC 和重复执行判断。
用户已确认按 R1 教程成功刷入并进入桌面；声音修正在当前系统上确认有效，补齐指纹库后
fprintd 已枚举到设备，用户确认指纹入口出现、功能正常。
但 R3 完整擦除重装以及从原厂未合并布局开始的完整流程尚未确认实机验收，不能将离线
核对视为上述完整流程的验证。本轮只在线修正运行文件，未再次刷写当前平板。

## 2. 安装会改哪些分区

| 操作 | 分区 | 内容 |
| --- | --- | --- |
| 原厂布局：擦除 | userdata、super | 删除 Android 系统和所有用户数据 |
| 原厂布局：刷写 | super | 临时放置 8 GiB 干净 Ubuntu ext4，供离线合并 |
| 原厂布局：首次引导合并 | GPT 的 super / userdata 条目 | 移除 super，userdata 起点前移 8 GiB |
| 已合并布局：擦除后刷写 | userdata | 直接安装同一干净 Ubuntu ext4 |
| 刷写 | boot_a、boot_b | #530 内核、原已验证 DTB、清理后的 initramfs |
| 刷写 | recovery_a、recovery_b | 同一 Ubuntu 启动镜像，避免 BCB 恢复启动选到旧内核 |
| 刷写 | dtbo_a、dtbo_b | 与主线 DTB 匹配的已验证 DTBO |
| 刷写 | vbmeta_a、vbmeta_b | 已验证的关闭 Android 镜像校验配置 |
| 设置 | A 槽 | 设为默认启动槽 |

合并后仅保留一个 userdata，编号仍为 `/dev/sda18`，容量 **124827545600 字节，约 116.25 GiB**；
比原 userdata 多 8 GiB。文件系统可用空间会扣除系统文件和 ext4 元数据。

合并由本包 initramfs 在正式挂载 Ubuntu 根目录前完成：

1. 验证本机 GPT 主副表、4 KiB 扇区、容量和分区相邻关系；验证新刷入 ext4 的 UUID、标签和大小。
2. 将**目标平板自己的** GPT 元数据保存到新系统的
   `/var/lib/j716f-first-boot/gpt-before/`，同时留一份于内存。
3. 卸载临时根目录；确认目标 UFS LUN 没有已挂载分区、系统没有活动 swap。
4. 只删除第 17 项 super、把第 18 项 userdata 的起点前移，重算 CRC；
   userdata 的 GUID、类型、属性、终点及其他分区条目保持原样。
5. 先写副 GPT，再写主 GPT，每步读回核对；失败时尝试恢复原元数据并停在救援界面。
6. 成功后**自动重启一次**，重新识别新分区布局，再将 ext4 扩容到整个 userdata。

电脑不会直接刷入其他平板的 GPT。本包不覆盖 xbl、abl、tz、modem、dsp、persist、fpinfo 等。
设置活动槽及首次成功启动标记会更新必要的 A/B 启动元数据。
首次 Ubuntu 启动还会在 BCB 包含已知 Android 恢复/临时引导请求时，备份 misc 并只清除
其前 32 字节命令，其余字节逐一核对不变；未知命令保留并记入初始化记录。

**原厂 super 和 userdata 都会清空，两个启动槽都安装 Ubuntu。**
这不是 Android/Ubuntu 双系统方案；恢复 Android 需要对应型号的原厂恢复包及恢复原厂分区布局。

## 3. 刷机前准备

1. 在 Android 中备份照片、文档、聊天资料、验证器等所有需要的数据。
2. 准备该型号对应的原厂恢复包，并保存到电脑，避免需要恢复时再寻找。
3. 确认实物型号为 **TB-J716F 128GB**，电量足够，并使用可靠的数据线。
4. 将本安装 ZIP 完整解压到电脑的一个目录，不能直接在 ZIP 内运行脚本。
5. 安装 Python 3.9 或以上。Windows 可用 `py -3 --version`，Linux 用 `python3 --version`。
6. 从 [Google 官方页面](https://developer.android.com/tools/releases/platform-tools)
   下载适合电脑系统的 SDK Platform-Tools，解压后把整个 `platform-tools` 文件夹放在
   `flash.py` 旁边。也可用 `--fastboot` 指定已有 fastboot 的完整路径。

目录应类似：

```text
j716f-ubuntu-22.04-clean-530-r3/
├── 刷机教程.md
├── manifest.json
├── SHA256SUMS
├── flash.py
├── flash-windows.cmd
├── flash-linux.sh
├── platform-tools/              # 自行下载的 Google 官方工具
│   ├── fastboot.exe / fastboot
│   └── adb.exe / adb
└── images/
    ├── boot.img
    ├── dtbo.img
    ├── vbmeta.img
    └── userdata.img             # Android sparse 格式，不是压缩包
```

### Bootloader 未解锁时

先按联想针对该型号、固件版本的流程完成解锁，再使用本安装包。
[ZUI 官方解锁入口](https://www.zui.com/iunlock) 是否接受该设备，需以页面及设备实际结果为准。
本包不提供设备专属解锁文件，不自动执行解锁，也不假定某条通用解锁命令对所有 ZUI 版本可用。
解锁通常会清空用户数据；这是 Android 的
[Bootloader 解锁行为](https://source.android.com/docs/core/architecture/bootloader/locking_unlocking)。

## 4. 从 Android 进入 fastboot

如果 Android 仍可操作：启用开发者选项中的 USB 调试，连接电脑，允许调试授权。

Windows PowerShell，在 `platform-tools` 目录执行：

```powershell
.\adb.exe devices
.\adb.exe reboot bootloader
.\fastboot.exe devices
```

Linux，在 `platform-tools` 目录执行：

```sh
./adb devices
./adb reboot bootloader
./fastboot devices
```

应看到一台设备的序列号及 `fastboot`。需要的是 **bootloader fastboot**，不是 Android 的
fastbootd。若电脑未识别，请先处理 USB 数据线和驱动/权限，不要开始刷写。
如果 Android 无法启动，使用该平板的实体按键进入 bootloader fastboot。

## 5. 推荐：使用随包脚本

回到 `flash.py` 所在目录。脚本会先检查所有镜像的完整 SHA-256，再检查设备、
解锁状态以及全部目标分区尺寸；任何不匹配都会停止。

### 先做只读预检

Windows：

```powershell
py -3 .\flash.py --dry-run
```

Linux：

```sh
python3 ./flash.py --dry-run
```

`--dry-run` 不擦除、不刷写、不切槽、不重启。
离线核对文件、只打印步骤可用 `--plan`，不需要连接设备。

### 正式安装

Windows 双击 `flash-windows.cmd`，或执行：

```powershell
py -3 .\flash.py
```

Linux：

```sh
bash ./flash-linux.sh
```

如果 Linux 提示 USB 权限不足，可在确认目录和文件正确后使用 `sudo python3 ./flash.py`。
自定义工具路径示例：

```sh
python3 ./flash.py --fastboot /完整路径/platform-tools/fastboot
```

一次只连接一台待刷平板；也可以用 `--serial 设备序列号` 明确选择。
脚本会再次要求确认实物型号和数据备份，只有输入：

```text
FLASH TB-J716F
```

才开始擦除及写入。`product` 有时只显示通用 SoC 名称，不能代替实物型号确认。

原厂布局流程：擦除 userdata 和 super → 将根镜像刷到 super → 刷双槽启动及配套镜像 →
设置 A → 启动到安装 initramfs → 备份 GPT、合并分区 → 自动重启 → 扩容并进入 Ubuntu。

已合并布局流程：擦除 userdata → 将根镜像刷到 userdata → 刷双槽启动及配套镜像 →
设置 A → 重启 → 扩容并进入 Ubuntu。

大镜像会分多段发送，持续数分钟是正常现象。刷写与首次合并过程中不要拔线、断电或手动重启。

某一步出现 `FAILED` 或脚本停止时，先保留 fastboot 界面，记录具体错误。
脚本不会在失败后继续下一步或自动重启；处理问题后重新完整执行。
如需刷完暂不重启，使用 `--no-reboot`。

## 6. 手工命令（仅在脚本预检通过后使用）

以下以 fastboot 已在 PATH 中为例；Windows 可改成 `.\platform-tools\fastboot.exe`。
如连接多台设备，每条命令都必须加 `-s 序列号`。每条命令成功后才继续下一条。

**根据预检报告，只选择下面一个根镜像写入分支，不能两个都执行。**

原厂布局（报告 `layout: stock`，super 为 8 GiB）：

```sh
fastboot erase userdata
fastboot erase super
fastboot -S 64M flash super images/userdata.img
```

已合并布局（报告 `layout: merged`，没有 super）：

```sh
fastboot erase userdata
fastboot -S 64M flash userdata images/userdata.img
```

然后，两种布局均继续执行：

```sh
fastboot -S 64M flash boot_a images/boot.img
fastboot -S 64M flash boot_b images/boot.img
fastboot -S 64M flash recovery_a images/boot.img
fastboot -S 64M flash recovery_b images/boot.img
fastboot flash dtbo_a images/dtbo.img
fastboot flash dtbo_b images/dtbo.img
fastboot flash vbmeta_a images/vbmeta.img
fastboot flash vbmeta_b images/vbmeta.img
fastboot set_active a
fastboot reboot
```

`-S 64M` 让 fastboot 分段发送较大的稀疏镜像。
**刷完不要再运行 `fastboot -w`、`fastboot format userdata` 或 `erase userdata`，
这些命令会删除刚安装的 Ubuntu。不要重新锁定 Bootloader。**
fastboot 的刷分区和活动槽语义可参阅
[AOSP fastboot 文档](https://android.googlesource.com/platform/system/core/+/refs/heads/main/fastboot/README.md)。
这里刷写的是物理 super 分区，不是其中的 system/vendor 逻辑分区；分区结构说明见
[AOSP 动态分区文档](https://source.android.com/docs/core/ota/dynamic_partitions/implement)。
本包将 super 改作安装暂存，并在 Linux 内合并，所刷文件不是 Android 的动态分区 super.img。

## 7. 第一次进入 Ubuntu

1. 首次启动预留约 2–5 分钟。原厂布局先合并 super 与 userdata，并自动多重启一次；
   第二次启动扩容文件系统。不要在中途断电。已合并布局不再执行 GPT 变更。
2. 登录用户名：**ubuntu**；初始密码：**ubuntu**。选择 GNOME Xorg 会话。
3. 登录后立即在终端运行 `passwd`，设置自己的密码。
4. 重新连接 Wi-Fi、配对蓝牙；在用户设置中重新录入指纹。包内没有原来的指纹。
5. 默认保留 150% 显示设置，显示选项为 100%、150%、200%，光标大小为 32。
6. 手动亮度、环境光、触控、麦克风和四扬声器的当前修复均已保留。
7. 新账户自动启用桌面音频服务；不再安装 Speaker Test 测试程序。
8. 指纹在“设置 → 用户”中重新录入；旧模板按干净安装要求清除。

SSH 只监听 USB 网络 `172.16.30.1`，用户名 `ubuntu`。主机密钥首次启动生成，
机器 ID 也会重新生成。桌面个人文件、历史日志、浏览器资料、配对与指纹均从空白开始。
GPS 未加入支持范围；新装后睡眠和长时间运行仍应自行复核。

首次初始化记录：`/var/lib/j716f-first-boot/complete.json`。
合并前 GPT 元数据及变更计划：`/var/lib/j716f-first-boot/gpt-before/`。
安装完成后建议另将此目录保存到电脑；它只备份分区表，不备份原 Android 系统或个人数据。
当前槽成功标记记录：`/var/lib/j716f-first-boot/slot-success.json`。
四扬声器开机配置记录：`/var/lib/j716f-speakers/stereo-530-mixer.json`。
四扬声器运行脚本：`/usr/local/libexec/j716f-configure-speakers.py`；不要因移除测试程序而删除它。

## 8. 排错与恢复

### 无法发现 fastboot 设备

确认屏幕是 bootloader fastboot、USB 线可传数据。Windows 检查设备管理器中的
Android Bootloader 驱动；Linux 检查 USB 权限。先让 `fastboot devices` 正常再继续。

### 提示 locked / flashing is not allowed

停止；先完成该型号对应的 Bootloader 解锁。本脚本不会代替解锁流程。

### R1 已安装但完全无声

先检查并启用当前用户音频服务，无需重新刷写：

```sh
systemctl --user enable --now pulseaudio.service pulseaudio.socket
pactl info
```

本机内置默认输出应为 `Speaker`，输入为 `J716F_Microphone`。R2/R3 已将用户服务启用设置
纳入系统默认。声音仍异常时，另检查静音、音量与 `speaker-mixer.service` 状态。

### R1/R2 设置没有指纹选项

R3 已包含 `/opt/j716f-fingerprint/lib/aarch64-linux-gnu/libfprint-2.so.2.0.0` 及
`/opt/j716f-fingerprint/lib/security/pam_fprintd.so`。前者用于枚举设备，后者是既有 GDM
指纹配置引用的 Ubuntu 官方 PAM 模块。旧版本若漏了这两项，可在线补齐公共运行文件，
不必重新清空安装；不要复制其他用户的指纹库，也不要放宽系统认证策略来绕过缺失文件。

### 分区尺寸不匹配

不要删除检查或照搬别的设备 GPT。保存型号、`fastboot getvar product` 和目标分区大小，
先重新审核设备布局。本包只对前述 TB-J716F 128GB 布局生成。

### 合并中断或 GPT 校验失败

程序会停止进入救援，不会跳过检查继续挂载根目录。保存屏幕错误、`dmesg` 及 GPT 备份。
若成功写入后因断电造成主副表不一致，需要根据**该目标平板自己的**备份进行恢复；
不要将包中或其他平板的分区表直接写入。正常自动合并不会移动已刷入的根文件系统数据。
救援中 `sda17` 或 `sda18` 的内核视图可能仍为重启前布局；未核对前不要格式化、扩容或尝试通用分区命令。

### 启动后返回 fastboot

确认 boot、recovery、dtbo、vbmeta 四组都已成功写入，执行 `fastboot set_active a`
再重启。不要只刷 boot，或把 Android 原 DTBO 与本包的主线 DTB 混用。

### 进入早期 USB 救援界面

根分区不能挂载、没有本安装包标记或 boot-guard 连续启动失败时，initramfs 会保留
USB 网络并提供 `172.16.30.1:23` 的 Telnet 救援。电脑 USB 网卡可配置
`172.16.30.2`、掩码 `255.255.255.128`，不设网关，再连接：

```sh
ping 172.16.30.1
telnet 172.16.30.1
```

正常 Ubuntu 启动不会开放这个 Telnet 服务；可使用前述 USB SSH。
先保留 `dmesg`、挂载和初始化服务错误，再处理；不要随意格式化或恢复别人的 GPT。

### 恢复 Android

使用本机型匹配的原厂完整恢复包及对应流程，并恢复原厂 super/userdata 分区布局。
此安装覆盖双槽启动镜像并清空 super、userdata，
单独切换 A/B 无法恢复原 Android 或其个人数据。persist、fpinfo 和底层固件没有被本包覆盖。
本包没有提供或要求刷写其他机器的校准、安全及解锁文件。
