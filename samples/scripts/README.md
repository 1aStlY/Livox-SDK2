# MID-360 静态 IP 配置脚本

`set_mid360_static_ip.py` 直接按 Livox SDK2 命令协议封包并通过 UDP 下发 `kCommandIDLidarWorkModeControl(0x0100)`，其中 Key 使用 `kKeyLidarIpCfg(0x0004)`，可用于修改 MID-360 静态 IP。

## 用法

```bash
python3 samples/scripts/set_mid360_static_ip.py \
  --lidar-ip 192.168.1.3 \
  --new-ip 192.168.1.10 \
  --netmask 255.255.255.0 \
  --gateway 192.168.1.1
```

## 参数说明

- `--lidar-ip`: 当前雷达 IP（命令发送目标 IP）
- `--new-ip`: 要设置的新静态 IP
- `--netmask`: 子网掩码
- `--gateway`: 网关
- `--port`: MID-360 命令端口，默认 `56100`
- `--bind-ip`: 本地绑定 IP，默认 `0.0.0.0`
- `--bind-port`: 本地绑定端口，默认 `0`（系统随机）
- `--timeout`: ACK 等待超时（秒）
- `--retry`: 超时后的重试次数

> 配置成功后雷达将切换到新 IP，请将主机网卡切到同网段再继续通信。
