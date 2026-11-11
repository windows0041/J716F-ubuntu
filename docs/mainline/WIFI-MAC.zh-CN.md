# Wi-Fi 固定地址与旧连接修复

部分固件启动时向 ath11k 提供的初始 MAC 会变化。旧连接若保存了
`802-11-wireless.mac-address` 或接口名约束，重启后可能被 NetworkManager
拒绝，日志显示 MAC 地址不匹配或接口名不匹配。

在平板执行：

```sh
sudo python3 tools/network/install-stable-wifi-mac.py
```

脚本根据本机持久化的 `/etc/machine-id` 生成本机唯一、固定的本地管理单播
MAC，通过 systemd `.link` 在设备创建时设置，并通过 NetworkManager 默认值
和现有连接的 cloned-mac-address 保持一致。保留系统原有接口命名策略，移除
旧 Wi-Fi 连接的 MAC 与接口名约束，不修改密码。适用于本项目只有一张
ath11k_pci 无线网卡的 J716F；不要把生成后的配置直接复制给其他设备。

修改前的 Netplan、NetworkManager 连接和已有配置保存在平板
`/var/backups/j716f-wifi/`，目录只允许 root 访问，其中可能包含已保存的密码。
仓库不包含实际 SSID、密码、设备 MAC 或机器 ID。需要恢复时先保存当前配置，
再从相应备份恢复文件并重新加载网络配置。

安装后重新连接 Wi-Fi；再正常重启，检查以下结果：

```sh
nmcli -f DEVICE,STATE,CONNECTION device
ip -brief link
```

MAC 应保持一致，已保存的连接应自动连接。若仍提示输入密码，需检查该连接
是否保存了系统密码，或用户密钥环是否已解锁；这与 MAC 修正分别处理。

2026-11-12 已在本机正常重启后验证：接口名保持原命名策略，MAC 保持一致，
已保存的目标 Wi-Fi 在开机后自动关联并取得局域网地址。

机制参考：[NetworkManager 配置手册](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/NetworkManager.conf.html)、
[systemd.link](https://www.freedesktop.org/software/systemd/man/latest/systemd.link.html)。
