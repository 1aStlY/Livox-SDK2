#!/usr/bin/env python3
"""Set MID-360 static IP with Livox SDK2 command protocol.

Protocol mapping comes from SDK2 source:
- cmd_id: 0x0100 (kCommandIDLidarWorkModeControl)
- key:    0x0004 (kKeyLidarIpCfg)
- lidar cmd port: 56100 (kMid360LidarCmdPort)
"""

from __future__ import annotations

import argparse
import ipaddress
import socket
import struct
import sys
import time
from typing import Tuple

SOF = 0xAA
VERSION = 0x00
CMD_ID_WORK_MODE_CTRL = 0x0100
CMD_TYPE_CMD = 0
SENDER_TYPE_HOST = 0
MID360_CMD_PORT = 56100
KEY_LIDAR_IP_CFG = 0x0004


def crc16_ccitt(data: bytes, init: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE, matching FastCRC16::ccitt used by SDK2."""
    crc = init
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def build_payload(new_ip: str, netmask: str, gateway: str) -> bytes:
    ip_bytes = ipaddress.IPv4Address(new_ip).packed
    mask_bytes = ipaddress.IPv4Address(netmask).packed
    gw_bytes = ipaddress.IPv4Address(gateway).packed

    # BuildRequest::BuildSetLidarIPInfoRequest in SDK2.
    key_num = 1
    reserved = 0
    value = ip_bytes + mask_bytes + gw_bytes  # LivoxLidarIpInfoValue (12 bytes)
    kv = struct.pack("<HH", KEY_LIDAR_IP_CFG, len(value)) + value
    return struct.pack("<HH", key_num, reserved) + kv


def build_packet(seq: int, payload: bytes) -> bytes:
    length = 22 + len(payload)  # sizeof(SdkPacket)-1 in sdk_protocol.cpp
    header_wo_crc = struct.pack(
        "<BBHIHBB6s",
        SOF,
        VERSION,
        length,
        seq,
        CMD_ID_WORK_MODE_CTRL,
        CMD_TYPE_CMD,
        SENDER_TYPE_HOST,
        b"\x00" * 6,
    )
    crc16_h = crc16_ccitt(header_wo_crc)
    # SDK uses standard CRC32 on payload bytes.
    import zlib

    crc32_d = zlib.crc32(payload) & 0xFFFFFFFF if payload else 0
    return header_wo_crc + struct.pack("<HI", crc16_h, crc32_d) + payload


def parse_ack(data: bytes, expected_seq: int) -> Tuple[int, int]:
    if len(data) < 25:
        raise ValueError(f"ack too short: {len(data)}")

    sof, ver, length, seq, cmd_id, cmd_type, sender_type, _rsvd, crc16_h, crc32_d = struct.unpack(
        "<BBHIHBB6sHI", data[:22]
    )
    if sof != SOF or ver != VERSION:
        raise ValueError("invalid SOF/version")
    if length != len(data):
        raise ValueError(f"invalid length field: {length}, actual: {len(data)}")

    calc_crc16 = crc16_ccitt(data[:18])
    if crc16_h != calc_crc16:
        raise ValueError(f"crc16 mismatch: recv={crc16_h:#06x}, calc={calc_crc16:#06x}")

    payload = data[22:]
    import zlib

    calc_crc32 = zlib.crc32(payload) & 0xFFFFFFFF if payload else 0
    if crc32_d != calc_crc32:
        raise ValueError(f"crc32 mismatch: recv={crc32_d:#010x}, calc={calc_crc32:#010x}")

    if seq != expected_seq:
        raise ValueError(f"seq mismatch: recv={seq}, expected={expected_seq}")
    if cmd_id != CMD_ID_WORK_MODE_CTRL:
        raise ValueError(f"cmd id mismatch: recv={cmd_id:#06x}")
    if cmd_type != 1:
        raise ValueError(f"unexpected cmd_type: {cmd_type}")
    if sender_type != 1:
        raise ValueError(f"unexpected sender_type: {sender_type}")
    if len(payload) < 3:
        raise ValueError("ack payload too short")

    ret_code, error_key = struct.unpack("<BH", payload[:3])
    return ret_code, error_key


def main() -> int:
    parser = argparse.ArgumentParser(description="Set MID-360 static IP via Livox SDK2 protocol packet")
    parser.add_argument("--lidar-ip", required=True, help="Current MID-360 IP (destination IP)")
    parser.add_argument("--new-ip", required=True, help="New static IP for MID-360")
    parser.add_argument("--netmask", required=True, help="Subnet mask, e.g. 255.255.255.0")
    parser.add_argument("--gateway", required=True, help="Gateway, e.g. 192.168.1.1")
    parser.add_argument("--port", type=int, default=MID360_CMD_PORT, help="MID-360 command port (default 56100)")
    parser.add_argument("--bind-ip", default="0.0.0.0", help="Local source IP to bind")
    parser.add_argument("--bind-port", type=int, default=0, help="Local source port (0 means random)")
    parser.add_argument("--timeout", type=float, default=1.5, help="Socket receive timeout in seconds")
    parser.add_argument("--retry", type=int, default=3, help="Retry count when timeout occurs")
    args = parser.parse_args()

    # Validate IPv4 strings early.
    for s in (args.lidar_ip, args.new_ip, args.netmask, args.gateway, args.bind_ip):
        ipaddress.IPv4Address(s)

    payload = build_payload(args.new_ip, args.netmask, args.gateway)
    seq = int(time.time()) & 0xFFFFFFFF
    packet = build_packet(seq, payload)

    dst = (args.lidar_ip, args.port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind_ip, args.bind_port))
    sock.settimeout(args.timeout)

    try:
        for i in range(1, args.retry + 1):
            sock.sendto(packet, dst)
            try:
                ack, peer = sock.recvfrom(2048)
                ret_code, error_key = parse_ack(ack, seq)
                if ret_code == 0 and error_key == 0:
                    print(f"[OK] MID-360 static IP set success. ack from {peer[0]}:{peer[1]}")
                    print(f"[OK] New IP should become: {args.new_ip}")
                    return 0

                print(
                    f"[FAIL] Device returned ret_code={ret_code}, error_key=0x{error_key:04x}",
                    file=sys.stderr,
                )
                return 2
            except socket.timeout:
                if i == args.retry:
                    print("[FAIL] Timeout waiting for ACK.", file=sys.stderr)
                    return 3
                print(f"[WARN] Timeout on try {i}/{args.retry}, retrying...")
    finally:
        sock.close()

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
