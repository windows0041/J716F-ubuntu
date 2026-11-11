#!/usr/bin/env python3
"""Keep ath11k Wi-Fi addressing stable without embedding device credentials."""

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def main():
    if os.geteuid():
        raise SystemExit("Run as root on the tablet.")
    machine_id = Path("/etc/machine-id").read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{32}", machine_id):
        raise SystemExit("A persistent, valid /etc/machine-id is required.")
    interfaces = [p for p in Path("/sys/class/net").iterdir()
                  if (p / "device/driver").resolve().name == "ath11k_pci"]
    if not interfaces:
        raise SystemExit("No ath11k_pci Wi-Fi interface found.")

    address = bytearray(hashlib.sha256(
        b"j716f-wifi-mac-v1:" + machine_id.encode()).digest()[:6])
    address[0] = (address[0] & 0xfc) | 0x02
    mac = ":".join(f"{byte:02x}" for byte in address)

    backup = Path("/var/backups/j716f-wifi") / time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, mode=0o700)
    for directory in ("/etc/netplan", "/etc/NetworkManager/system-connections"):
        source = Path(directory)
        if source.exists():
            shutil.copytree(source, backup / source.name)
    files = {
        Path("/etc/systemd/network/10-j716f-wifi-mac.link"):
            "[Match]\nDriver=ath11k_pci\n\n[Link]\n"
            "NamePolicy=keep kernel database onboard slot path\n"
            "AlternativeNamesPolicy=database onboard slot path\n"
            f"MACAddressPolicy=none\nMACAddress={mac}\n",
        Path("/etc/NetworkManager/conf.d/91-j716f-wifi-mac.conf"):
            "[device-j716f-wifi]\nmatch-device=driver:ath11k_pci\n"
            "wifi.scan-rand-mac-address=no\n\n"
            "[connection-j716f-wifi]\nmatch-device=driver:ath11k_pci\n"
            f"wifi.cloned-mac-address={mac}\n",
    }
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, backup / path.name)
        path.write_text(text)
        path.chmod(0o644)

    for line in run("nmcli", "-t", "-f", "UUID,TYPE", "connection", "show").splitlines():
        uuid, kind = line.split(":", 1)
        if kind != "802-11-wireless":
            continue
        # Let NetworkManager/Netplan persist the update and retain saved secrets.
        run("nmcli", "connection", "modify", uuid,
            "802-11-wireless.mac-address", "",
            "802-11-wireless.cloned-mac-address", mac,
            "connection.interface-name", "")
    run("nmcli", "general", "reload", "conf")
    print(f"Stable Wi-Fi MAC: {mac}\nPrivate backup: {backup}")
    print("Reconnect Wi-Fi to apply now; the link rule also applies on boot.")


if __name__ == "__main__":
    main()
