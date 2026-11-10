# 项目结构

当前 7.4/26.10 主线版本以 [主线构建说明](mainline/BUILD.zh-CN.md) 和 [状态](mainline/STATUS.zh-CN.md) 为入口。下表主要描述保留的 R3 目录；主线新增 configs/ubuntu、tools/power 与对应组合补丁，不复制完整 Linux 7.4 源树。

为保持已有构建脚本可用，大型工作目录留在原位置，Git 只记录整理后的源码入口。

| 目录 | 内容 |
| --- | --- |
| `docs/` | 当前安装、状态、构建和来源说明 |
| `docs/releases/` | R3 发布清单、镜像摘要和 ZIP 校验值；没有镜像本体 |
| `configs/kernel/` | 最终 #530 配置 |
| `configs/audio/` | 四扬声器开机配置和 PulseAudio 路由 |
| `configs/fingerprint/` | GDM 指纹 PAM 配置 |
| `configs/initramfs/` | R3 initramfs 的 init 参考源码 |
| `patches/kernel/` | 相对原版 Linux 6.15.11 的完整改动及来源摘要 |
| `patches/userspace/` | libfprint J716F 驱动改动 |
| `tools/release/` | 镜像导出、清理、初始化、合并、安装及修正脚本 |
| `tools/project/` | 源码快照和本地仓库检查工具 |
| `tools/input/`、`tools/sensors/` | 输入与传感器运行脚本 |
| `tools/display-scaling/` | 当前显示修正源码、补丁和构建脚本 |
| `tools/stability/` | 稳定性记录服务与配置 |
| `tools/fingerprint-system/` | 用户态构建入口、服务单元及控制程序源码 |
| `mkbootimg-aosp/` | AOSP 启动镜像工具 |

## 更新来源快照

本机保留相应源树和原版 tarball 时，可运行：

```sh
python3 tools/project/snapshot-kernel.py
python3 tools/project/snapshot-userspace.py
```

它们只读取构建源树，生成补丁、版本和摘要，不修改内核或嵌套上游仓库。
生成后检查差异，再更新提交。`tools/release` 依赖的私有构建缓存及公开运行库产物没有自动放进 Git。
