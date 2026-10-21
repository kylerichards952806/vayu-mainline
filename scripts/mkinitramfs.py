#!/usr/bin/env python3
"""Build and verify the vayu initramfs (newc cpio, optionally LZ4).

The ramdisk this produces holds one static arm64 binary, `/init`, plus the
directories it mounts. It is deliberately not a busybox image: at this stage the
job is to get a kernel that can say who it is, mount pstore and stay alive, not
to provide a userland.

Compression: the stock Android ramdisk on this device is an **LZ4 legacy
frame**, and the kernel is built with `CONFIG_RD_LZ4=y`, so `--lz4` writes the
same container with the `lz4 -l` tool. Without that tool the archive is written
uncompressed, which the kernel also accepts, and says so instead of pretending.

    ./scripts/mkinitramfs.py build --init init.aarch64 -o ramdisk.cpio.lz4 --lz4
    ./scripts/mkinitramfs.py verify --image ramdisk.cpio.lz4 --expect-init init.aarch64
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

NEWC_MAGIC = b"070701"
TRAILER = "TRAILER!!!"
MODE_DIR = 0o040755
MODE_FILE = 0o100644
MODE_EXEC = 0o100755


def _entry(name: str, mode: int, data: bytes = b"", ino: int = 0) -> bytes:
    """One newc header plus its payload, padded to four bytes."""
    payload = data
    fields = [
        ino, mode, 0, 0, 1, 0, len(payload), 0, 0, 0, 0, len(name) + 1, 0,
    ]
    header = NEWC_MAGIC + b"".join(b"%08X" % f for f in fields)
    out = bytearray(header)
    out += name.encode() + b"\0"
    out += b"\0" * ((-len(out)) % 4)
    out += payload
    out += b"\0" * ((-len(payload)) % 4)
    return bytes(out)


def build_cpio(init: bytes, dirs: list[str], files: dict[str, bytes]) -> bytes:
    out = bytearray()
    out += _entry(".", MODE_DIR, ino=1)
    for index, name in enumerate(dirs, start=2):
        out += _entry(name.rstrip("/"), MODE_DIR, ino=index)
    out += _entry("init", MODE_EXEC, init, ino=100)
    for index, (name, data) in enumerate(files.items(), start=101):
        out += _entry(name, MODE_FILE, data, ino=index)
    out += _entry(TRAILER, 0, ino=0)
    # The kernel pads the archive to a 512-byte boundary before looking at it.
    out += b"\0" * ((-len(out)) % 512)
    return bytes(out)


def parse_cpio(data: bytes) -> list[dict]:
    entries = []
    offset = 0
    while offset + 110 <= len(data):
        if data[offset:offset + 6] != NEWC_MAGIC:
            raise SystemExit(f"not a newc cpio archive at offset {offset}")
        fields = [int(data[offset + 6 + 8 * i:offset + 14 + 8 * i], 16)
                  for i in range(13)]
        mode, size, namelen = fields[1], fields[6], fields[11]
        name_start = offset + 110
        name = data[name_start:name_start + namelen - 1].decode(errors="replace")
        payload_start = name_start + namelen
        payload_start += (-payload_start) % 4
        payload = data[payload_start:payload_start + size]
        entries.append({"name": name, "mode": mode, "size": size,
                        "data": payload})
        offset = payload_start + size
        offset += (-offset) % 4
        if name == TRAILER:
            break
    return entries


def compress(data: bytes, want_lz4: bool) -> tuple[bytes, str]:
    if not want_lz4:
        return data, "uncompressed cpio"
    lz4 = shutil.which("lz4")
    if not lz4:
        print("lz4 not found on PATH; writing uncompressed cpio "
              "(the kernel accepts both)", file=sys.stderr)
        return data, "uncompressed cpio"
    result = subprocess.run([lz4, "-l", "-9", "-c"], input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise SystemExit(f"lz4 failed: {result.stderr.decode(errors='replace')}")
    return result.stdout, "lz4 legacy frame"


def decompress(data: bytes) -> tuple[bytes, str]:
    if data[:4] == b"\x02\x21\x4c\x18":
        lz4 = shutil.which("lz4")
        if not lz4:
            raise SystemExit("image is LZ4 but the lz4 tool is not on PATH")
        result = subprocess.run([lz4, "-d", "-c"], input=data,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise SystemExit("lz4 -d failed: "
                             + result.stderr.decode(errors="replace"))
        return result.stdout, "lz4 legacy frame"
    if data[:6] == NEWC_MAGIC:
        return data, "uncompressed cpio"
    raise SystemExit(f"unknown ramdisk container: {data[:4].hex()}")


def cmd_build(args: argparse.Namespace) -> int:
    init = Path(args.init).read_bytes()
    if init[:4] != b"\x7fELF":
        print(f"{args.init} is not an ELF binary", file=sys.stderr)
        return 1
    machine = struct.unpack_from("<H", init, 18)[0]
    if machine != 183:
        print(f"{args.init} is ELF machine {machine}, expected 183 (aarch64)",
              file=sys.stderr)
        return 1

    files = {}
    for spec in args.file:
        source, _, dest = spec.partition(":")
        files[dest or os.path.basename(source)] = Path(source).read_bytes()

    archive = build_cpio(init, args.dir, files)
    image, kind = compress(archive, args.lz4)
    Path(args.output).write_bytes(image)
    print(f"wrote {args.output}: {len(image):,} bytes ({kind})")
    print(f"  cpio {len(archive):,} bytes, init {len(init):,} bytes, "
          f"{len(args.dir)} directories, {len(files)} extra file(s)")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    data = Path(args.image).read_bytes()
    archive, kind = decompress(data)
    entries = parse_cpio(archive)
    failures = []

    def check(condition: bool, message: str) -> None:
        print(("ok   " if condition else "FAIL ") + message)
        if not condition:
            failures.append(message)

    names = {entry["name"]: entry for entry in entries}
    init = names.get("init")
    check("init" in names, "archive contains /init")
    if init:
        check(init["mode"] & 0o111 != 0,
              f"/init is executable (mode {init['mode'] & 0o7777:o})")
        check(init["data"][:4] == b"\x7fELF", "/init is an ELF binary")
        machine = struct.unpack_from("<H", init["data"], 18)[0]
        check(machine == 183, f"/init is aarch64 (machine {machine})")
        if args.expect_init:
            original = Path(args.expect_init).read_bytes()
            check(init["data"] == original,
                  "/init is byte-identical to the compiled binary")
    for directory in ("dev", "proc", "sys"):
        check(directory in names, f"archive contains /{directory}")
    check(entries[-1]["name"] == TRAILER, "archive ends with the cpio trailer")
    check(all(len(entry["name"]) for entry in entries), "every entry is named")

    print(f"     container: {kind}, {len(data):,} bytes, "
          f"{len(entries) - 1} entries")
    if args.expect_init:
        digest = hashlib.sha1(Path(args.expect_init).read_bytes()).hexdigest()
        print(f"     init sha1: {digest}")

    if failures:
        print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
        return 1
    print("\ninitramfs parses and every check passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="write the ramdisk")
    b.add_argument("--init", required=True, help="static aarch64 init binary")
    b.add_argument("--dir", action="append", default=[],
                   help="directory to create (repeatable)")
    b.add_argument("--file", action="append", default=[],
                   help="extra file as SOURCE:DEST (repeatable)")
    b.add_argument("--lz4", action="store_true",
                   help="write an LZ4 legacy frame, like the stock ramdisk")
    b.add_argument("-o", "--output", required=True)
    b.set_defaults(func=cmd_build)

    v = sub.add_parser("verify", help="parse a ramdisk and check it")
    v.add_argument("--image", required=True)
    v.add_argument("--expect-init", help="binary /init must match")
    v.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
