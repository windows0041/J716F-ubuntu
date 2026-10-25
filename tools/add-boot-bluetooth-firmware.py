#!/usr/bin/env python3
"""Add QCA6390 firmware to a v2 boot ramdisk without changing existing entries.

Only uncompressed Android v2 Images with gzip/newc ramdisks, no second stage,
and no recovery overlay are supported. Does not access the tablet. The original
image is never overwritten. The resulting manifest records hashes, not contents.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ("htbtfw20.tlv", "htnv20.bin")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def align(value, boundary):
    return (value + boundary - 1) // boundary * boundary


def boot_image(data):
    require(data[:8] == b"ANDROID!", "Not an Android boot image")
    require(len(data) >= 1660, "Truncated boot header")
    fields = struct.unpack_from("<10I", data, 8)
    ks, ka, rs, ra, second, second_addr, tags, page, version, osv = fields
    require(version == 2 and page == 4096, "Requires header v2, page size 4096")
    require(second == 0, "Second-stage boot payload is unsupported")
    recovery, recovery_offset, header_size, ds, da = struct.unpack_from("<IQIIQ", data, 1632)
    require(recovery == recovery_offset == 0, "Recovery overlay is unsupported")
    require(header_size == 1660, "Unexpected v2 header size")
    ro = page + align(ks, page)
    do = ro + align(rs, page)
    end = do + align(ds, page)
    require(len(data) == end, "Unexpected image length or appended signature/footer")
    require(ks and rs and ds, "Kernel, ramdisk and DTB must be nonempty")
    require(data[do:do + 4] == b"\xd0\x0d\xfe\xed", "DTB is not FDT")
    require(data[ro:ro + 2] == b"\x1f\x8b", "Ramdisk is not gzip")
    return dict(kernel=data[page:page + ks], ramdisk=data[ro:ro + rs],
                dtb=data[do:do + ds], page=page, kernel_addr=ka,
                ramdisk_addr=ra, second_addr=second_addr, tags_addr=tags,
                dtb_addr=da, os_version=osv, ramdisk_offset=ro, dtb_offset=do,
                board=data[48:64].rstrip(b"\0").decode("ascii"),
                cmdline=(data[64:576].split(b"\0", 1)[0] +
                         data[608:1632].split(b"\0", 1)[0]).decode("ascii"))


def cpio_entries(data):
    entries = []
    offset = 0
    while offset + 110 <= len(data):
        header = data[offset:offset + 110]
        require(header[:6] == b"070701", "Requires a newc archive (070701)")
        fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        namesize, size = fields[11], fields[6]
        require(namesize > 0, "Empty cpio name")
        name_end = offset + 110 + namesize
        require(name_end <= len(data), "Truncated cpio name")
        name_bytes = data[offset + 110:name_end]
        require(name_bytes[-1:] == b"\0", "Unterminated cpio name")
        name = name_bytes[:-1].decode("utf-8")
        data_offset = align(name_end, 4)
        end = align(data_offset + size, 4)
        require(end <= len(data), "Truncated cpio data")
        entries.append(dict(name=name, fields=fields, raw=data[offset:end],
                            data=data[data_offset:data_offset + size], offset=offset))
        offset = end
        if name == "TRAILER!!!":
            require(not any(data[offset:]), "Nonzero data after cpio trailer")
            return entries
    raise ValueError("Missing cpio trailer")


def new_entry(name, contents, inode, directory=False):
    encoded = name.encode("utf-8") + b"\0"
    mode = stat.S_IFDIR | 0o755 if directory else stat.S_IFREG | 0o644
    fields = [inode, mode, 0, 0, 2 if directory else 1, 0,
              len(contents), 0, 0, 0, 0, len(encoded), 0]
    blob = b"070701" + b"".join(f"{value:08x}".encode() for value in fields) + encoded
    blob += b"\0" * (-len(blob) % 4)
    blob += contents
    return blob + b"\0" * (-len(blob) % 4)


def entry_manifest(entry):
    return dict(path=entry["name"], size=len(entry["data"]),
                metadata=entry["fields"], sha256=sha(entry["data"]),
                raw_entry_sha256=sha(entry["raw"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--firmware-dir", type=Path, default=ROOT / "firmware/qca")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    require(source != output, "Source and output must be different files")
    original = source.read_bytes()
    old = boot_image(original)
    archive = gzip.decompress(old["ramdisk"])
    entries = cpio_entries(archive)
    names = {entry["name"].removeprefix("./") for entry in entries}
    required = {"lib/firmware/qca", *("lib/firmware/qca/" + name for name in FIRMWARE)}
    require(not names.intersection(required), "QCA firmware entries already exist")
    require("lib/firmware" in names, "Missing parent lib/firmware directory")
    inode = max(entry["fields"][0] for entry in entries) + 1
    firmware = [(name, (args.firmware_dir / name).read_bytes()) for name in FIRMWARE]
    require(all(data for _, data in firmware), "Empty QCA firmware file")
    added = new_entry("lib/firmware/qca", b"", inode, directory=True)
    for index, (name, data) in enumerate(firmware, 1):
        added += new_entry("lib/firmware/qca/" + name, data, inode + index)
    trailer = entries[-1]["offset"]
    rebuilt_archive = archive[:trailer] + added + archive[trailer:]
    rebuilt_archive += b"\0" * (-len(rebuilt_archive) % 512)
    new_entries = cpio_entries(rebuilt_archive)
    preserved = new_entries[:len(entries) - 1] + [new_entries[-1]]
    require([entry["raw"] for entry in entries] == [entry["raw"] for entry in preserved],
            "Original cpio metadata/data changed")
    require(rebuilt_archive[:trailer] == archive[:trailer], "Original archive prefix changed")
    added_entries = new_entries[len(entries) - 1:-1]
    require(len(added_entries) == 3, "Unexpected number of appended entries")
    ramdisk = gzip.compress(rebuilt_archive, compresslevel=9, mtime=0)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="j716f-bt-repack-") as temp:
        work = Path(temp)
        for name, data in (("Image", old["kernel"]), ("ramdisk.gz", ramdisk), ("board.dtb", old["dtb"])):
            (work / name).write_bytes(data)
        packed = work / "boot.img"
        cmd = [sys.executable, str(ROOT / "mkbootimg-aosp/mkbootimg.py"),
               "--kernel", str(work / "Image"), "--ramdisk", str(work / "ramdisk.gz"),
               "--dtb", str(work / "board.dtb"), "--pagesize", str(old["page"]),
               "--base", "0", "--kernel_offset", str(old["kernel_addr"]),
               "--ramdisk_offset", str(old["ramdisk_addr"]),
               "--second_offset", str(old["second_addr"]), "--tags_offset", str(old["tags_addr"]),
               "--dtb_offset", str(old["dtb_addr"]), "--header_version", "2",
               "--board", old["board"], "--cmdline", old["cmdline"], "-o", str(packed)]
        osv = old["os_version"] >> 11
        patch = old["os_version"] & 0x7ff
        if osv:
            cmd += ["--os_version", f"{osv >> 14}.{(osv >> 7) & 127}.{osv & 127}"]
        if patch:
            cmd += ["--os_patch_level", f"{(patch >> 4) + 2000:04}-{patch & 15:02}"]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        result = packed.read_bytes()
        new = boot_image(result)
        require(new["kernel"] == old["kernel"], "Kernel payload changed")
        require(new["dtb"] == old["dtb"], "DTB payload changed")
        require(new["ramdisk"] == ramdisk, "Ramdisk payload differs from appended archive")
        require(gzip.decompress(new["ramdisk"]) == rebuilt_archive, "Gzip roundtrip mismatch")
        # Ramdisk size and the content-derived image ID are the only header changes.
        allowed = set(range(16, 20)) | set(range(576, 608))
        changed = [i for i in range(old["page"]) if original[i] != result[i]]
        require(all(i in allowed for i in changed), "Unexpected boot header/padding change")
        verified = subprocess.run([sys.executable, str(ROOT / "verify-bootimg.py"), str(packed)],
                                  check=True, capture_output=True, text=True)
    # All payload and layout checks must pass before publishing the candidate.
    temporary_output = output.with_name(output.name + ".tmp")
    temporary_output.write_bytes(result)
    os.replace(temporary_output, output)
    verify_path = output.with_suffix(output.suffix + ".verification.log")
    verify_path.write_text(verified.stdout + verified.stderr)
    manifest = dict(source=dict(path=str(source), size=len(original), sha256=sha(original)),
                    output=dict(path=str(output), size=len(result), sha256=sha(result)),
                    kernel=dict(size=len(old["kernel"]), sha256=sha(old["kernel"]), unchanged=True),
                    dtb=dict(size=len(old["dtb"]), sha256=sha(old["dtb"]), unchanged=True),
                    ramdisk=dict(original_size=len(old["ramdisk"]), original_sha256=sha(old["ramdisk"]),
                                 size=len(ramdisk), sha256=sha(ramdisk), cpio_sha256=sha(rebuilt_archive)),
                    layout=dict(header_version=2, page_size=old["page"],
                                kernel_addr=old["kernel_addr"], ramdisk_addr=old["ramdisk_addr"],
                                tags_addr=old["tags_addr"], dtb_addr=old["dtb_addr"],
                                ramdisk_offset=new["ramdisk_offset"], dtb_offset=new["dtb_offset"],
                                cmdline_sha256=sha(old["cmdline"].encode()), header_changes=changed),
                    original_entries_preserved=len(entries),
                    original_entries=[entry_manifest(entry) for entry in entries],
                    added_entries=[entry_manifest(entry) for entry in added_entries],
                    verification_log=str(verify_path))
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(dict(output=manifest["output"], manifest=str(manifest_path),
                          verification_log=str(verify_path), original_entries_preserved=len(entries),
                          added_entries=manifest["added_entries"]), indent=2))


if __name__ == "__main__":
    main()
