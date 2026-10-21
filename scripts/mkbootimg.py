#!/usr/bin/env python3
"""Build and verify a vayu boot image in the Android header-v2 format.

vayu (POCO X3 Pro) has no vendor_boot partition: kernel, ramdisk and DTBs all
live in `boot`, described by a `boot_img_hdr_v1`/`v2` header. The values below
are the ones this device's own boot image carries, taken from
`BoardConfigCommon.mk` in the official LineageOS trees and confirmed against a
boot image pulled from the phone (page size 4096, base 0x0, `Image` loaded at
0x8000, ramdisk at 0x01000000, DTB at 0x01f00000, header version 2).

Two subcommands:

    mkbootimg.py build  --kernel Image --dtb vayu.dtb -o boot.img
    mkbootimg.py verify --image boot.img --expect-kernel Image --expect-dtb vayu.dtb

`verify` re-parses the produced file from scratch: magic, header version, header
size, page alignment of every section, the SHA-1 `id` field recomputed over the
payload, the DTB magic and model string, and optionally that the payloads are
byte-identical to the inputs. It also accepts a boot image this script did not
write - point it at a stock image and it reports the same fields.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

MAGIC = b"ANDROID!"
PAGE_SIZE = 4096

# Offsets inside the fixed part of the header.
F_MAGIC = 0
F_KERNEL_SIZE = 8
F_KERNEL_ADDR = 12
F_RAMDISK_SIZE = 16
F_RAMDISK_ADDR = 20
F_SECOND_SIZE = 24
F_SECOND_ADDR = 28
F_TAGS_ADDR = 32
F_PAGE_SIZE = 36
F_HEADER_VERSION = 40
F_OS_VERSION = 44
F_NAME = 48          # 16 bytes
F_CMDLINE = 64       # 512 bytes
F_ID = 576           # 8 bytes
F_EXTRA_CMDLINE = 608  # 1024 bytes
F_RECOVERY_DTBO_SIZE = 1632
F_RECOVERY_DTBO_OFFSET = 1636
F_HEADER_SIZE = 1644
F_DTB_SIZE = 1648
F_DTB_ADDR = 1652
V2_HEADER_SIZE = 1660

# Values this device boots with.
KERNEL_ADDR = 0x00008000
RAMDISK_ADDR = 0x01000000
SECOND_ADDR = 0x00000000
TAGS_ADDR = 0x00000100
DTB_ADDR = 0x01F00000
NAME = b"vayu"

# Settings > About phone > Kernel version is `uname -r`; the bootloader does
# not read this, but the header carries the Android release it belongs to so
# that `fastboot getvar` and recovery agree with the ROM. Encoded as
# (major << 25) | (minor << 18) | (patch << 11) | (year << 4) | month.
OS_VERSION = (17 << 25) | (0 << 18) | (0 << 11) | (26 << 4) | 10

# BOARD_KERNEL_CMDLINE from the sm8150-common board config, plus the two lines
# vayu's device config appends.
CMDLINE = (
    "androidboot.hardware=qcom androidboot.console=ttyMSM0 androidboot.memcg=1 "
    "lpm_levels.sleep_disabled=1 msm_rtb.filter=0x237 service_locator.enable=1 "
    "swiotlb=2048 loop.max_part=7 androidboot.usbcontroller=a600000.dwc3 "
    "androidboot.fstab_suffix=qcom androidboot.init_fatal_reboot_target=recovery"
)

CMD_MAX = 512
EXTRA_CMD_MAX = 1024
NAME_MAX = 16


def align(value: int, page: int = PAGE_SIZE) -> int:
    return (value + page - 1) // page * page


def payload_id(kernel: bytes, ramdisk: bytes, second: bytes,
               recovery_dtbo: bytes, dtb: bytes) -> bytes:
    """The header's `id` field: SHA-1 over each payload and its length.

    This is what AOSP's mkbootimg writes for header v2. Verified by
    recomputing it over a boot image taken from the device and matching the
    stored field exactly.
    """
    digest = hashlib.sha1()
    for part in (kernel, ramdisk, second, recovery_dtbo, dtb):
        digest.update(part)
        digest.update(struct.pack("<I", len(part)))
    return digest.digest()


def ramdisk_kind(data: bytes) -> str:
    """Name the compression of a ramdisk, as Android's unpackers see it."""
    if not data:
        return "empty"
    if data[:4] == b"\x02\x21\x4c\x18":
        return "lz4 legacy frame (the format vayu's stock ramdisk uses)"
    if data[:4] == b"\x04\x22\x4d\x18":
        return "lz4 frame"
    if data[:2] == b"\x1f\x8b":
        return "gzip"
    if data[:6] == b"\xfd7zXZ\x00":
        return "xz"
    if data[:4] == b"\x28\xb5\x2f\xfd":
        return "zstd"
    if data[:6] == b"070701" or data[:6] == b"070702":
        return "uncompressed cpio"
    return "unknown"


def ramdisk_from_boot(path: str) -> bytes:
    """Pull the ramdisk out of an existing boot image.

    This is how a build that has no initramfs of its own reuses the one the
    device already boots: point it at the boot image read off the phone (the
    5.4 LineageOS image) and the packer keeps that payload verbatim.
    """
    info = parse(Path(path).read_bytes())
    if info["ramdisk_size"] == 0:
        raise SystemExit(f"{path} has no ramdisk")
    return info["ramdisk"]


def build(args: argparse.Namespace) -> int:
    kernel = Path(args.kernel).read_bytes()
    # Optional: this device's reference boot image has dtb_size 0 and takes its
    # tree from the dtbo partition, so --dtb is only for other layouts.
    dtb = Path(args.dtb).read_bytes() if args.dtb else b""
    if args.ramdisk and args.ramdisk_from_boot:
        print("give --ramdisk or --ramdisk-from-boot, not both", file=sys.stderr)
        return 1
    if args.ramdisk_from_boot:
        ramdisk = ramdisk_from_boot(args.ramdisk_from_boot)
        print(f"ramdisk: {len(ramdisk):,} bytes from {args.ramdisk_from_boot} "
              f"({ramdisk_kind(ramdisk)})")
    else:
        ramdisk = Path(args.ramdisk).read_bytes() if args.ramdisk else b""
    second = Path(args.second).read_bytes() if args.second else b""
    recovery_dtbo = (Path(args.recovery_dtbo).read_bytes()
                     if args.recovery_dtbo else b"")

    if dtb and dtb[:4] != b"\xd0\x0d\xfe\xed":
        print(f"{args.dtb} is not a flattened device tree", file=sys.stderr)
        return 1

    name = args.name.encode()
    cmdline = args.cmdline.encode()
    if len(name) + 1 > NAME_MAX:
        print(f"name is {len(name)} bytes; the header field is {NAME_MAX}",
              file=sys.stderr)
        return 1
    if len(cmdline) + 1 > CMD_MAX:
        print(f"cmdline is {len(cmdline)} bytes; the header field is {CMD_MAX}",
              file=sys.stderr)
        return 1
    if len(NAME) + 1 > NAME_MAX:
        print("internal error: name does not fit", file=sys.stderr)
        return 1

    header = bytearray(V2_HEADER_SIZE)
    header[F_MAGIC:F_MAGIC + 8] = MAGIC
    struct.pack_into("<I", header, F_KERNEL_SIZE, len(kernel))
    struct.pack_into("<I", header, F_KERNEL_ADDR, args.kernel_addr)
    struct.pack_into("<I", header, F_RAMDISK_SIZE, len(ramdisk))
    struct.pack_into("<I", header, F_RAMDISK_ADDR, args.ramdisk_addr)
    struct.pack_into("<I", header, F_SECOND_SIZE, len(second))
    struct.pack_into("<I", header, F_SECOND_ADDR, args.second_addr)
    struct.pack_into("<I", header, F_TAGS_ADDR, args.tags_addr)
    struct.pack_into("<I", header, F_PAGE_SIZE, PAGE_SIZE)
    struct.pack_into("<I", header, F_HEADER_VERSION, 2)
    struct.pack_into("<I", header, F_OS_VERSION, args.os_version)
    header[F_NAME:F_NAME + len(name)] = name
    header[F_CMDLINE:F_CMDLINE + len(cmdline)] = cmdline
    header[F_ID:F_ID + 8] = payload_id(kernel, ramdisk, second,
                                       recovery_dtbo, dtb)
    struct.pack_into("<I", header, F_RECOVERY_DTBO_SIZE, len(recovery_dtbo))
    struct.pack_into("<Q", header, F_RECOVERY_DTBO_OFFSET, 0)
    struct.pack_into("<I", header, F_HEADER_SIZE, V2_HEADER_SIZE)
    struct.pack_into("<I", header, F_DTB_SIZE, len(dtb))
    struct.pack_into("<Q", header, F_DTB_ADDR, args.dtb_addr)

    out = bytearray()
    out += bytes(header)
    out += bytes(align(V2_HEADER_SIZE) - len(header))     # pad header to page
    out += kernel
    out += bytes(align(len(kernel)) - len(kernel))
    out += ramdisk
    out += bytes(align(len(ramdisk)) - len(ramdisk))
    out += second
    out += bytes(align(len(second)) - len(second))
    out += recovery_dtbo
    out += bytes(align(len(recovery_dtbo)) - len(recovery_dtbo))
    out += dtb
    out += bytes(align(len(dtb)) - len(dtb))              # DTB padded to page

    if args.partition_size:
        if len(out) > args.partition_size:
            print(f"image is {len(out)} bytes, larger than the "
                  f"{args.partition_size}-byte partition", file=sys.stderr)
            return 1
        out += bytes(args.partition_size - len(out))

    Path(args.output).write_bytes(bytes(out))
    print(f"wrote {args.output}: {len(out):,} bytes "
          f"(kernel {len(kernel):,}, ramdisk {len(ramdisk):,}, "
          f"dtb {len(dtb):,}, page {PAGE_SIZE}, header v2)")
    return 0


def parse(data: bytes) -> dict:
    if data[:8] != MAGIC:
        raise SystemExit(f"not an Android boot image: magic is {data[:8]!r}")
    (
        kernel_size, kernel_addr, ramdisk_size, ramdisk_addr,
        second_size, second_addr, tags_addr, page_size,
        header_version, os_version,
    ) = struct.unpack_from("<10I", data, 8)
    info = {
        "kernel_size": kernel_size,
        "kernel_addr": kernel_addr,
        "ramdisk_size": ramdisk_size,
        "ramdisk_addr": ramdisk_addr,
        "second_size": second_size,
        "second_addr": second_addr,
        "tags_addr": tags_addr,
        "page_size": page_size,
        "header_version": header_version,
        "os_version": os_version,
        "name": data[F_NAME:F_NAME + NAME_MAX].split(b"\0")[0],
        "cmdline": data[F_CMDLINE:F_CMDLINE + CMD_MAX].split(b"\0")[0],
        "id": data[F_ID:F_ID + 8],
        "extra_cmdline": data[F_EXTRA_CMDLINE:
                              F_EXTRA_CMDLINE + EXTRA_CMD_MAX].split(b"\0")[0],
    }

    info["recovery_dtbo_size"] = 0
    info["header_size"] = 0
    info["dtb_size"] = 0
    info["dtb_addr"] = 0
    if header_version >= 1:
        info["recovery_dtbo_size"] = struct.unpack_from("<I", data,
                                                        F_RECOVERY_DTBO_SIZE)[0]
        info["header_size"] = struct.unpack_from("<I", data, F_HEADER_SIZE)[0]
    if header_version >= 2:
        info["dtb_size"] = struct.unpack_from("<I", data, F_DTB_SIZE)[0]
        info["dtb_addr"] = struct.unpack_from("<Q", data, F_DTB_ADDR)[0]

    page = page_size
    offset = page
    info["kernel_offset"] = offset
    info["kernel"] = data[offset:offset + kernel_size]
    offset += align(kernel_size, page)
    info["ramdisk_offset"] = offset
    info["ramdisk"] = data[offset:offset + ramdisk_size]
    offset += align(ramdisk_size, page)
    info["second_offset"] = offset
    info["second"] = data[offset:offset + second_size]
    offset += align(second_size, page)
    info["recovery_dtbo_offset"] = offset
    info["recovery_dtbo"] = data[offset:offset + info["recovery_dtbo_size"]]
    offset += align(info["recovery_dtbo_size"], page)
    info["dtb_offset"] = offset
    info["dtb"] = data[offset:offset + info["dtb_size"]]
    info["end_of_payload"] = offset + info["dtb_size"]
    return info


def verify(args: argparse.Namespace) -> int:
    data = Path(args.image).read_bytes()
    info = parse(data)
    failures: list[str] = []

    def check(condition: bool, message: str) -> None:
        if condition:
            print(f"ok   {message}")
        else:
            print(f"FAIL {message}")
            failures.append(message)

    check(info["header_version"] == 2,
          f"header version is 2 (got {info['header_version']})")
    check(info["header_size"] == V2_HEADER_SIZE,
          f"header size is {V2_HEADER_SIZE} (got {info['header_size']})")
    check(info["page_size"] == PAGE_SIZE,
          f"page size is {PAGE_SIZE} (got {info['page_size']})")
    check(info["kernel_size"] > 0, f"kernel payload present "
          f"({info['kernel_size']:,} bytes)")
    check(info["kernel"][56:60] == b"ARMd",
          "kernel is an arm64 Image (ARMd magic)")
    if info["dtb_size"]:
        check(info["dtb"][:4] == b"\xd0\x0d\xfe\xed",
              "dtb is a flattened device tree")
        check(info["dtb_addr"] == DTB_ADDR,
              f"dtb load address is {DTB_ADDR:#x} "
              f"(got {info['dtb_addr']:#x})")
    else:
        print("     dtb: none in this image (vayu takes its tree from dtbo)")
    print(f"     ramdisk: {info['ramdisk_size']:,} bytes, "
          f"{ramdisk_kind(info['ramdisk'])}")
    check(info["kernel_addr"] == KERNEL_ADDR,
          f"kernel load address is {KERNEL_ADDR:#x} (got {info['kernel_addr']:#x})")
    check(info["ramdisk_addr"] == RAMDISK_ADDR,
          f"ramdisk load address is {RAMDISK_ADDR:#x} "
          f"(got {info['ramdisk_addr']:#x})")

    # The header stores the first 8 bytes of the SHA-1, not all 20.
    expected_id = payload_id(info["kernel"], info["ramdisk"], info["second"],
                             info["recovery_dtbo"], info["dtb"])[:8]
    check(info["id"] == expected_id,
          f"id field matches SHA-1 over the payload ({expected_id.hex()})")

    page = info["page_size"]
    check(info["kernel_offset"] % page == 0
          and info["ramdisk_offset"] % page == 0
          and info["second_offset"] % page == 0
          and info["dtb_offset"] % page == 0,
          "every section starts on a page boundary")

    if args.expect_model:
        check(args.expect_model.encode() in info["dtb"],
              f"dtb contains the model string {args.expect_model!r}")
    print(f"     sections: kernel @ {info['kernel_offset']:#x}, "
          f"ramdisk @ {info['ramdisk_offset']:#x}, "
          f"dtb @ {info['dtb_offset']:#x}, "
          f"payload ends at {info['end_of_payload']:,} of {len(data):,} bytes")

    if args.kernel_release:
        check(args.kernel_release.encode() in info["kernel"],
              f"kernel carries {args.kernel_release}")

    if args.expect_kernel:
        original = Path(args.expect_kernel).read_bytes()
        check(info["kernel"] == original,
              "kernel payload is byte-identical to the input Image")
    if args.expect_dtb:
        original = Path(args.expect_dtb).read_bytes()
        check(info["dtb"] == original,
              "dtb payload is byte-identical to the input DTB")
    if args.expect_ramdisk:
        original = Path(args.expect_ramdisk).read_bytes()
        check(info["ramdisk"] == original,
              "ramdisk payload is byte-identical to the input ramdisk")

    if failures:
        print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
        return 1
    print("\nboot image parses and every check passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="write a header-v2 boot image")
    b.add_argument("--kernel", required=True, help="arm64 Image")
    b.add_argument("--dtb", help="flattened device tree to append (optional; "
                                 "vayu takes its tree from the dtbo partition)")
    b.add_argument("--ramdisk", help="ramdisk image (optional for a kernel-only build)")
    b.add_argument("--ramdisk-from-boot", metavar="BOOT_IMG",
                   help="reuse the ramdisk from an existing boot image, e.g. the "
                        "stock 5.4 android boot image read off the device")
    b.add_argument("--second", help="second stage payload")
    b.add_argument("--recovery-dtbo", help="recovery DTBO payload")
    b.add_argument("--name", default=NAME.decode())
    b.add_argument("--cmdline", default=CMDLINE)
    b.add_argument("--os-version", type=lambda v: int(v, 0), default=OS_VERSION)
    b.add_argument("--kernel-addr", type=lambda v: int(v, 0), default=KERNEL_ADDR)
    b.add_argument("--ramdisk-addr", type=lambda v: int(v, 0), default=RAMDISK_ADDR)
    b.add_argument("--second-addr", type=lambda v: int(v, 0), default=SECOND_ADDR)
    b.add_argument("--tags-addr", type=lambda v: int(v, 0), default=TAGS_ADDR)
    b.add_argument("--dtb-addr", type=lambda v: int(v, 0), default=DTB_ADDR)
    b.add_argument("--partition-size", type=lambda v: int(v, 0),
                   help="zero-pad the output to this size (vayu's boot is 128 MiB)")
    b.add_argument("-o", "--output", required=True)
    b.set_defaults(func=build)

    v = sub.add_parser("verify", help="parse a boot image and check it")
    v.add_argument("--image", required=True)
    v.add_argument("--expect-kernel")
    v.add_argument("--expect-dtb")
    v.add_argument("--expect-ramdisk")
    v.add_argument("--kernel-release", help="string the kernel must carry, e.g. 6.18.32-vayu")
    v.add_argument("--expect-model",
                   help="string the dtb must contain, e.g. 'Xiaomi POCO X3 Pro'")
    v.set_defaults(func=verify)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
