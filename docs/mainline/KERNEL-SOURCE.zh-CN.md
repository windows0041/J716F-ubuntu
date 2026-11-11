# 内核完整源码与来源验证

完整源码位于 `kernel/linux-7.4-rc2`，包括固定上游的原始文件、56 文件移植组合补丁和 `j716f.config`。不是子模块或下载链接；旧 6.15 源码另行保留。

本次在原完整快照上同步已测试的 NB7VPQ904M 驱动和 USB 配置，将原先在实机以 DT 覆盖层应用的 USB 拓扑整合入板级 DTS，并补充对应 binding。除这些明确变更及模块配置外，保留原有源码内容。当前快照与重新校验、干净解压并应用最终组合补丁的源树逐个文件比较内容和模式，配置对应重建树的 `.config`；这与此前直接逐个比较旧调试构建树的验证方式分开记录。

共 97,370 个源码条目，约 1.56 GiB。精确字节数、SHA-256 清单、来源和暂存 Git 子树对象见 [kernel-source-manifest.json](kernel-source-manifest.json)，并与 [sources.json](sources.json) 中的补丁及配置摘要对应。上游测试和文档素材保留，不加入生成头文件、对象、模块或启动镜像。

## 重建和暂存验证

按 [构建说明](BUILD.zh-CN.md) 使用 `prepare-mainline.py` 从固定上游归档生成独立源码树。`snapshot-mainline-source.py` 用于尚不存在快照目录时的重新导出，需要实际参考源码树，拒绝覆盖当前快照。

暂存源码后，执行 `python3 tools/project/verify-kernel-snapshot.py --record-index-tree` 逐个读取 Git 对象核对内容和文件模式，记录子树，再暂存更新后的清单。不带该选项则只验证。`audit-staged.py` 只豁免精确匹配来源清单的内核子树；其余改动继续扫描敏感信息。

仓库属性关闭完整快照的自动换行转换。若稀疏检出未展开源码，可运行 `git sparse-checkout add kernel/linux-7.4-rc2`；建议在 WSL 的 Linux 文件系统中构建。
