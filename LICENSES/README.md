# 来源与许可

本项目组合了多个上游组件；保留各文件头和原组件许可，不对整仓库统一改签许可。

| 组件 | 来源/版本 | 许可记录 |
| --- | --- | --- |
| Linux 内核及相关补丁 | 原版 Linux 6.15.11 + 本机 #530 改动 | `Linux-GPL-2.0.txt`，并遵循各文件 SPDX |
| libfprint J716F 驱动 | `docs/UPSTREAMS.json` 中固定提交及本地补丁 | `libfprint-goodix-qsee.txt`，LGPL 2.1 |
| qsee-supplicant | 固定上游提交，本地无代码修改 | `qsee-supplicant.txt` |
| Goodix SPI 参考驱动 | 固定上游提交 | `goodix-fp-spi-linux.txt` |
| AOSP mkbootimg | 工具内版权与许可头 | Apache-2.0，见工具文件头 |
| Xorg modesetting 修改 | 当前补丁内保留原代码来源 | 遵循对应 Xorg 文件许可 |

仅以补丁保存的第三方代码仍受其原许可约束。未声明许可的原创文件未在此次本地整理中新增对外许可授权。
固件、Chrome 等第三方二进制及完整 Ubuntu 镜像没有纳入本仓库。
