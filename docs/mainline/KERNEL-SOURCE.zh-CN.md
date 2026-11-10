# 已调试内核的完整源码快照

完整源码路径为 kernel/linux-7.4-rc2，包含固定上游版本的全部原始文件、当前 53 文件移植补丁及实机配置 j716f.config。不是空壳目录、子模块或仅供下载的链接。

导出采用固定归档校验→干净解压→应用组合补丁→逐文件比较的方法，而不是复制已有编译目录。每个导出的普通文件都与调试开发树中的对应文件核对 SHA-256，符号链接核对目标；j716f.config 对应开发树的 .config。上游原始素材和文件模式保留，不额外纳入生成头文件、对象、模块、vmlinux 或启动镜像。

来源、总文件数、字节数、内容清单摘要和 Git 子树对象记录在 [kernel-source-manifest.json](kernel-source-manifest.json)。此清单与组合补丁、配置的摘要相互对应。

当前快照共 97,370 个条目，约 1.56 GiB，Git 子树为
`1e55937ff1586ae8070f9809b55ab000233765d1`。Git 对象重新读回后，内容与模式清单摘要仍为
`c3938d70fafd724037166080522912005b99b0a2a948137d165fafd228f9820e`，
与导出时一致。分离构建的配置、J716F DTB 也已与原调试树核对一致。

## 本地重新导出

工具入口为 tools/project/snapshot-mainline-source.py，需要固定的上游归档、已调试的参考源树和一个尚不存在的目标源码目录。工具拒绝覆盖现有快照，不访问平板或执行刷写。

```sh
python3 tools/project/snapshot-mainline-source.py \
  --archive /path/to/linux-7.4-rc2.tar.gz \
  --reference-tree /path/to/debugged-linux-tree
```

重新导出后需要审核并更新 Git 子树摘要。暂存审计只对精确匹配来源清单的内核子树豁免普通二进制/测试素材限制；对子树做任何变更而不更新来源清单，审计都会失败。其他配置、脚本和文档继续执行敏感信息扫描。

在暂存源码后，可用 `python3 tools/project/verify-kernel-snapshot.py --record-index-tree`
逐个读取 Git 对象验证内容和模式，并记录子树；再暂存更新后的清单。
不带该选项时只验证，不更新清单。仓库属性关闭此快照的自动换行转换，避免改变原始源文件。

使用稀疏检出的工作区可能没有展开 kernel 目录，这不表示提交中缺少源码。可用 `git ls-tree HEAD kernel/linux-7.4-rc2` 检查 Git 对象，或 `git sparse-checkout add kernel/linux-7.4-rc2` 展开。建议将完整检出和构建放在 WSL 的 Linux 文件系统。
