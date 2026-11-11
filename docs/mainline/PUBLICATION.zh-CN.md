# GitHub 主线与发布范围

更新日期：2026-11-11。默认分支 `main` 现以 Linux 7.4-rc2 / Ubuntu 26.10 ARM64 为项目当前开发主线，原有提交历史和 6.15 源码保留。`publish/linux-7.4-ubuntu-26.10` 同步当前版本；这里的“主线”指项目开发分支，内核仍固定在 sources.json 的上游提交。

仓库包含完整内核源码、55 文件组合补丁、内核配置、构建与来源验证工具，以及音频、指纹、充电、USB 网络、国内软件源和静默启动等通用运行配置。源码数量、摘要和 Git 子树对象见 [源码清单](kernel-source-manifest.json)。

不上传固件、Image/模块、boot/rootfs 镜像、构建缓存、GPT 备份、原始日志、录音截图、设备 UUID、密钥、密码、指纹模板、Wi-Fi 凭据或绑定单台设备的安装/刷写脚本。尚未发布通用安装镜像。

## 本次同步的验证

- 固定上游归档校验后干净解压并应用更新组合补丁，全部源码条目与仓库快照逐项比较；暂存后再次读取 Git 对象核对内容和模式摘要。
- 更新配置通过 olddefconfig 一致性检查，新增 NB7VPQ904M 模块与 J716F DTB 交叉编译；只对本次内核增量执行 checkpatch。此前的完整内核及实机测试范围见 [状态](STATUS.zh-CN.md)，本次未重新构建完整 Image 或刷写平板。
- USB 运行时覆盖层整合入板级 DTS，新增 mux 的 binding 描述。对重建源码、模块和设备树做离线检查，不能替代 USB 3.x、OTG、PD 或外接屏实测。
- Shell 语法、文档本地链接、暂存差异空白及敏感信息审计通过。日常 initramfs 清理后的重启与桌面输入已由用户确认。

同步含 AI 辅助整理及代码集成；保留原组件许可与上游来源，不添加工具生成的 Signed-off-by，也没有向维护者发送补丁。

## 提交前复核入口

```sh
git diff --cached --check
python3 tools/project/verify-kernel-snapshot.py
python3 tools/project/audit-staged.py
```

暂存审计只豁免与来源清单精确匹配的完整内核子树，其余新增或修改文件执行普通敏感信息扫描；不改写或承诺审计全部旧历史。
