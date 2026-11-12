# 仓库与数据边界

项目的既有 GitHub 仓库为
[windows0041/J716F-ubuntu](https://github.com/windows0041/J716F-ubuntu)。
更新日期：2026-11-12。本地 `origin` 指向 `https://github.com/windows0041/J716F-ubuntu.git`。GitHub 默认分支为 `main`，当前开发目标是 Linux 7.4-rc2 / Ubuntu 26.10；`publish/linux-7.4-ubuntu-26.10` 同步当前版本，旧版历史和 6.15.11 源码保留。发布内容及验证范围见 [主线发布说明](mainline/PUBLICATION.zh-CN.md)。

## 纳入版本管理

- 完整的 7.4 基础内核与旧 6.15.11 源码、各自补丁和配置。
- 独立相机模块源码、构建/安装工具及固定 Wi-Fi MAC 修复工具。
- 当前通用运行配置、验证工具及保留的 R3 镜像脚本。
- 精确上游提交、许可文件、构建说明、发布元数据与校验值。
- 基础内核完整快照与固定上游加补丁重建的源码逐项核对；不将嵌套 `.git` 作为缺失内容的子模块提交。

## 仅留在工作区

- `build/`、`kernel/dl/`、`out/`、生成的 Image/模块、工具链二进制和第三方源码缓存。
- `backup*/`、`artifacts*/`、`firmware/`、`logs/`、`releases/` 与旧版发布目录。
- 原始调试日志、大型镜像、磁盘/GPT 备份、录音截图、core 文件、设备唯一信息及历史连接配置。
- 旧的设备专用刷写脚本和包含个人连接信息的历史笔记。

这些类别不纳入版本管理；需要保留的本机备份由维护者单独管理。`.gitignore` 使用根目录白名单及产物排除规则，内核源码快照按来源清单例外核对。旧 README 的本地归档不进入版本管理。

## 提交与审计

提交前运行 `git diff --cached --check` 和 `python3 tools/project/audit-staged.py`，检查暂存差异空白、大文件、嵌套子模块和常见敏感信息。涉及基础内核快照时，还需按 [快照说明](mainline/KERNEL-SOURCE.zh-CN.md) 核对 Git 对象、文件模式和来源清单。

审计工具只打印问题类型与路径，范围是本次暂存新增/修改文件；不改写全部旧历史。源码核对、编译检查、实机运行和用户操作分别记录在主线文档中，不能互相替代。
