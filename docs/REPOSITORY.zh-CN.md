# 仓库与数据边界

项目的既有 GitHub 仓库为
[windows0041/J716F-ubuntu](https://github.com/windows0041/J716F-ubuntu)。
本地 `origin` 指向 `https://github.com/windows0041/J716F-ubuntu.git`。主线移植的待发布分支为 `publish/linux-7.4-ubuntu-26.10`；旧版历史保留。
远端可见性需在 GitHub 自行确认，本地整理不更改其权限。

## 纳入版本管理

- 当前源码补丁、内核配置、运行配置及 R3 镜像脚本。
- 精确上游提交、许可文件、构建说明、发布元数据与校验值。
- 固定上游树以来源记录和补丁保存，避免将嵌套 `.git` 意外提交成缺失内容的子模块。

## 仅留在工作区

- `build/`、`kernel/dl/`、`out/`、工具链二进制和已克隆的第三方源码缓存。
- `backup*/`、`artifacts*/`、`firmware/`、`logs/`、`releases/` 与旧版发布目录。
- 原始调试日志、大型镜像、磁盘/GPT 备份、录音截图、core 文件、设备唯一信息及历史连接配置。
- 旧的设备专用刷写脚本和包含个人连接信息的历史笔记。

以上文件没有被删除；`.gitignore` 使用根目录白名单，只让整理后的内容进入 Git。
原 README 保存在本地 `docs/local-history/README-before-local-git.md`，不进入版本管理。

## 首次本地提交

如果尚无个人 Git 身份，首个快照使用仓库级本地身份 `J716F Project <j716f@localhost>`。
它没有绑定 GitHub 账户，也没有改动全局 Git 配置。可在后续提交前自行设置本仓库的姓名和邮箱。

整理过程仅检查提交清单与敏感信息，不编译内核、不执行项目测试、不操作平板。

提交前可运行 `python3 tools/project/audit-staged.py`，检查本次暂存新增/修改文件的大文件、嵌套子模块和常见敏感信息；工具只打印问题类型与路径，不扫描或改写全部旧历史。
