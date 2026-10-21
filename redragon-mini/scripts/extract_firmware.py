#!/usr/bin/env python3
"""Statically extract the SINO overlay; never loads or executes the PE image.

This extraction is an analysis aid, not a firmware flashing procedure.
The custom cipher was translated from x86 methods 0x403230 and 0x4032D0.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct

MASK = 0xFFFFFFFF
DELTA = 0x9E3769B9  # Custom TEA variant, not the standard TEA delta.
MAGIC = b"\x5a\xa5SINO"


def crypt_block(block, key, decrypt=True):
    left, right = struct.unpack(">II", block)
    if decrypt:
        total = (DELTA * 32) & MASK
        for _ in range(32):
            right = (right - (((left << 4) + key[2]) ^
                             ((left >> 5) + key[3]) ^ (total + left))) & MASK
            left = (left - (((right << 4) + key[0]) ^
                           ((right >> 5) + key[1]) ^ (total + right))) & MASK
            total = (total - DELTA) & MASK
    else:
        total = 0
        for _ in range(32):
            total = (total + DELTA) & MASK
            left = (left + (((right << 4) + key[0]) ^
                           ((right >> 5) + key[1]) ^ (total + right))) & MASK
            right = (right + (((left << 4) + key[2]) ^
                             ((left >> 5) + key[3]) ^ (total + left))) & MASK
    return struct.pack(">II", left, right)


def crypt(data, key, decrypt=True):
    whole = len(data) // 8 * 8
    return b"".join(crypt_block(data[i:i + 8], key, decrypt)
                    for i in range(0, whole, 8)) + data[whole:]


def overlay_start(data):
    if data[:2] != b"MZ":
        raise ValueError("Input is not a PE image")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("Invalid PE signature")
    count = struct.unpack_from("<H", data, pe + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    table = pe + 24 + optional_size
    ends = []
    for i in range(count):
        size, offset = struct.unpack_from("<II", data, table + 40 * i + 16)
        ends.append(offset + size)
    return max(ends)


def extract(path, out):
    data = path.read_bytes()
    offset = overlay_start(data)
    overlay = data[offset:]
    if overlay[:6] != MAGIC:
        raise ValueError("Expected SINO overlay at end of PE sections")
    vendor_id, product_id, firmware_size = struct.unpack_from(">HHH", overlay, 6)
    encrypted = overlay[12:12 + firmware_size]
    if firmware_size % 8 or len(encrypted) != firmware_size:
        raise ValueError("Truncated or unaligned firmware")
    key = overlay[12 + firmware_size:16 + firmware_size]
    if len(key) != 4:
        raise ValueError("Missing four-byte cipher key")
    firmware = crypt(encrypted, key)
    if crypt(firmware, key, decrypt=False) != encrypted:
        raise ValueError("Cipher round trip failed")
    out.mkdir(parents=True, exist_ok=True)
    (out / "decrypted.bin").write_bytes(firmware)
    (out / "overlay.bin").write_bytes(overlay)
    metadata_size = overlay[16 + firmware_size]
    metadata = crypt(overlay[17 + firmware_size:
                             17 + firmware_size + metadata_size], key)
    (out / "metadata.bin").write_bytes(metadata)
    # The descriptor is found, not inferred from the updater's labels.
    descriptor = firmware.find(b"\x12\x01\x10\x01\x00\x00\x00\x08")
    descriptor_info = None
    if descriptor >= 0:
        vid, pid = struct.unpack_from("<HH", firmware, descriptor + 8)
        descriptor_info = {"offset": descriptor, "vid": f"{vid:04X}",
                           "pid": f"{pid:04X}"}
    report = {
        "input": path.name,
        "file_size": len(data),
        "file_sha256": hashlib.sha256(data).hexdigest(),
        "overlay_offset": offset,
        "overlay_size": len(overlay),
        "header_vid": f"{vendor_id:04X}",
        "header_pid": f"{product_id:04X}",
        "firmware_size": firmware_size,
        "firmware_sha256": hashlib.sha256(firmware).hexdigest(),
        "cipher_roundtrip": True,
        "reset_vector": firmware[:3].hex(" "),
        "usb_descriptor": descriptor_info,
    }
    (out / "extraction.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    print(json.dumps(extract(args.input, args.output), indent=2))
