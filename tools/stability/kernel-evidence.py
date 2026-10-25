#!/usr/bin/env python3
"""Bounded, event-driven kernel evidence. No resets, SysRq or user memory."""
from collections import deque
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

STATE = Path("/var/lib/j716f-stability")
CRITICAL = re.compile(r"hard LOCKUP|soft lockup|rcu:.*(?:stalls|starvation)|"
                      r"Error sending AMC RPMH|blocked for more than|"
                      r"BUG:|Kernel panic|EXT4-fs error|I/O error")
DISPLAY = re.compile(r"frame done timeout|failed wait_for_idle")


def command(args, limit=1024 * 1024):
    try:
        # Finite outputs only: no unbounded journal, memory or devcoredump reads.
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=5, check=False)
        return r.stdout[-limit:].decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return str(e)


def read(path, limit=128 * 1024):
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError as e:
        return str(e)


def snapshot():
    return {"uptime": read("/proc/uptime"),
            "memory": read("/proc/meminfo"),
            "interrupts": read("/proc/interrupts"),
            "softirqs": read("/proc/softirqs"),
            "pressure": {x: read("/proc/pressure/" + x) for x in ("cpu", "memory", "io")},
            "tasks": command(["ps", "-eLo", "pid,tid,psr,stat,wchan:32,comm"]),
            "services": command(["systemctl", "--failed", "--no-pager"])}


def main():
    if b"lenovo,j716f" not in Path("/proc/device-tree/compatible").read_bytes():
        raise SystemExit("Unsupported device")
    STATE.mkdir(mode=0o700, exist_ok=True)
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if not re.fullmatch(r"[0-9a-f-]{36}", boot):
        raise SystemExit("Invalid boot ID")
    current = STATE / ("boot-" + boot)
    current.mkdir(mode=0o700, exist_ok=True)
    dirs = [p for p in STATE.iterdir() if p.is_dir() and not p.is_symlink()
            and re.fullmatch(r"boot-[0-9a-f-]{36}", p.name)]
    keep = sorted((p for p in dirs if p != current), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    # Exact, validated collector-owned directories only; maximum four boots.
    for p in dirs:
        if p != current and p not in keep:
            shutil.rmtree(p)
    bootfile = current / "boot.json"
    if not bootfile.exists():
        bootfile.write_text(json.dumps({"boot_id": boot, "uname": command(["uname", "-a"]),
                                       "snapshot": snapshot()}, indent=2))
        (current / "kernel-at-start.log").write_text(command(["dmesg", "--color=never"], 2 * 1024 * 1024))
        for p in Path("/sys/fs/pstore").glob("*"):
            # Preserve console/kmsg only; never erase the kernel's original files.
            if p.name.startswith(("console-ramoops", "dmesg-ramoops")):
                (current / ("previous-pstore-" + p.name)).write_text(read(p, 1024 * 1024))
    captured = {kind for kind in ("display", "critical")
                if (current / (kind + "-fault.json")).exists()}
    recent = deque(maxlen=1024)
    follow = subprocess.Popen(["dmesg", "--follow", "--color=never"], stdout=subprocess.PIPE)
    try:
        for raw in iter(follow.stdout.readline, b""):
            line = raw[:4096].decode("utf-8", "replace")
            recent.append(line)
            kind = "critical" if CRITICAL.search(line) else "display" if DISPLAY.search(line) else None
            if kind and kind not in captured:
                # A display-only timeout must not consume the later lockup/RPMH snapshot.
                captured.add(kind)
                (current / (kind + "-fault-context.log")).write_text("".join(recent))
                (current / (kind + "-fault.json")).write_text(json.dumps({"trigger": line, "snapshot": snapshot()}, indent=2))
                print("Saved first " + kind + " kernel fault evidence for boot " + boot, flush=True)
        raise SystemExit("Kernel log follower stopped")
    finally:
        follow.terminate()
        try:
            follow.wait(timeout=2)
        except subprocess.TimeoutExpired:
            follow.kill()
            follow.wait()


if __name__ == "__main__":
    main()
