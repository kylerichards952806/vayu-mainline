#!/usr/bin/env python3
"""Write the `dtbo` partition image for vayu.

vayu's DTBO partition is 32 MiB of a DTBO table (`mkdtimg` format): a 32-byte
header, one 32-byte entry per device tree, then the trees themselves, the whole
thing padded to the partition size. The vendor image on the phone holds a single
291,547-byte base DTB at offset 64, entry id 0 rev 0, and an AVB footer at the
end - measured from `device/dtbo.img`, not assumed.

For a mainline kernel the partition should carry **no overlays**: the board
description in `boot.img` is complete, and stale vendor overlays applied on top
of it are how a mainline port ends up with no display. So the default here is a
valid table with zero entries, which ABL parses happily and applies nothing
from, rather than a raw block of zeros that it might reject.

`--dtb` embeds a tree the way the vendor image does, for anyone who wants to
mirror the reference layout exactly.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

MAGIC = 0xD7B7AB1E
HEADER_SIZE = 32
ENTRY_SIZE = 32
PAGE_SIZE = 4096
DTBO_PARTITION_SIZE = 32 * 1024 * 1024


def build(dtbs: list[bytes], out_size: int) -> bytes:
    total = HEADER_SIZE + ENTRY_SIZE * len(dtbs) + sum(len(d) for d in dtbs)
    if total > out_size:
        raise ValueError(f"{total} bytes of table and trees do not fit in "
                         f"{out_size}")

    out = bytearray(out_size)
    struct.pack_into(">8I", out, 0, MAGIC, total, HEADER_SIZE, ENTRY_SIZE,
                     len(dtbs), HEADER_SIZE, PAGE_SIZE, 0)

    offset = HEADER_SIZE + ENTRY_SIZE * len(dtbs)
    for index, dtb in enumerate(dtbs):
        # id 0 / rev 0 is what the vendor image uses, and it matches any board.
        struct.pack_into(">4I", out, HEADER_SIZE + index * ENTRY_SIZE,
                         len(dtb), offset, 0, 0)
        out[offset:offset + len(dtb)] = dtb
        offset += len(dtb)
    return bytes(out)


def describe(data: bytes) -> dict:
    magic, total, header, entry, count, entries_off, page, version = \
        struct.unpack_from(">8I", data, 0)
    info = {
        "magic": magic, "total_size": total, "header_size": header,
        "entry_size": entry, "count": count, "entries_offset": entries_off,
        "page_size": page, "version": version, "entries": [],
    }
    for index in range(count):
        size, offset, dt_id, rev = struct.unpack_from(
            ">4I", data, entries_off + index * entry)
        info["entries"].append((size, offset, dt_id, rev))
    return info


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="write a dtbo image")
    b.add_argument("--dtb", action="append", default=[],
                   help="embed this device tree (repeatable); default: none")
    b.add_argument("--size", type=lambda v: int(v, 0),
                   default=DTBO_PARTITION_SIZE)
    b.add_argument("-o", "--output", required=True)
    b.set_defaults(func=lambda a: _build(a))

    v = sub.add_parser("verify", help="parse a dtbo image")
    v.add_argument("--image", required=True)
    v.add_argument("--expect-size", type=lambda x: int(x, 0),
                   default=DTBO_PARTITION_SIZE)
    v.set_defaults(func=lambda a: _verify(a))

    args = parser.parse_args()
    return args.func(args)


def _build(args: argparse.Namespace) -> int:
    dtbs = [Path(p).read_bytes() for p in args.dtb]
    for path, dtb in zip(args.dtb, dtbs):
        if dtb[:4] != b"\xd0\x0d\xfe\xed":
            print(f"{path} is not a flattened device tree", file=sys.stderr)
            return 1
    data = build(dtbs, args.size)
    Path(args.output).write_bytes(data)
    print(f"wrote {args.output}: {len(data):,} bytes, "
          f"{len(dtbs)} entr{'y' if len(dtbs) == 1 else 'ies'}")
    return 0


def _verify(args: argparse.Namespace) -> int:
    data = Path(args.image).read_bytes()
    info = describe(data)
    failures = []

    def check(condition: bool, message: str) -> None:
        print(("ok   " if condition else "FAIL ") + message)
        if not condition:
            failures.append(message)

    check(len(data) == args.expect_size,
          f"image is {args.expect_size:,} bytes (got {len(data):,})")
    check(info["magic"] == MAGIC, "DTBO table magic is correct")
    check(info["header_size"] == HEADER_SIZE,
          f"header size is {HEADER_SIZE}")
    check(info["entry_size"] == ENTRY_SIZE, f"entry size is {ENTRY_SIZE}")
    check(info["entries_offset"] == HEADER_SIZE,
          "entries follow the header")
    check(info["page_size"] == PAGE_SIZE, f"page size is {PAGE_SIZE}")
    for index, (size, offset, _dt_id, _rev) in enumerate(info["entries"]):
        check(data[offset:offset + 4] == b"\xd0\x0d\xfe\xed",
              f"entry {index} points at a flattened device tree ({size} bytes)")
    check(not any(data[info["total_size"]:]),
          "everything after the table is zero padding")

    if failures:
        print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
        return 1
    print(f"\ndtbo image parses: {info['count']} entr"
          f"{'y' if info['count'] == 1 else 'ies'}, total {info['total_size']} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
