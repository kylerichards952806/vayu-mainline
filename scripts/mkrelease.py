#!/usr/bin/env python3
"""Build a TWRP-flashable kernel zip for vayu from a boot image and a DTBO.

The zip flashes two partitions: `boot` (our header-v2 kernel image) and `dtbo`.
vayu's DTBO partition holds the vendor overlay set that ABL applies on top of
whatever DTB the boot image carries, so a mainline kernel wants that partition
*cleared*: our device tree is a complete description of the board, and stale
vendor overlays are the difference between "no display" and a booting phone.
`--dtbo-size` writes such a blank DTBO (the partition is 32 MiB per the sm8150
common board config); `--dtbo FILE` flashes a real image instead, for anyone
who wants the vendor overlays back.

Naming, as requested for releases:

    <kernel-version>-<builder>-<device>-<date>.zip
    6.18.32-kyler084-vayu-2026-10-21.zip

`verify` unpacks the zip it is given and re-parses the boot image inside it, so
a green run means the artifact a recovery would actually flash is well formed,
not just that a file was written.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import zipfile
from datetime import date as date_cls
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mkdtbo  # noqa: E402  (same directory)
import mkbootimg  # noqa: E402  (same directory, used to parse the payload)

DEVICE = "vayu"
DTBO_PARTITION_SIZE = 32 * 1024 * 1024
UPDATER_SCRIPT = "#MAGIC\n# vayu-mainline: flashing is done by update-binary\n"

UPDATE_BINARY = r"""#!/sbin/sh
#
# vayu-mainline TWRP installer. Flashes boot.img and dtbo.img from this zip.
# Written for the shell update-binary interface TWRP supports, so it needs no
# edify and no companion tools beyond busybox.

OUTFD=/proc/self/fd/$2
ZIP=$3

ui_print() {
  echo "ui_print $1" > "$OUTFD"
  echo "ui_print" > "$OUTFD"
}

abort() {
  ui_print "! $1"
  exit 1
}

BYNAME=/dev/block/bootdevice/by-name
[ -d "$BYNAME" ] || BYNAME=/dev/block/by-name
[ -d "$BYNAME" ] || abort "no by-name partition directory; unknown device"

flash() {
  part=$1
  file=$2
  [ -f "$file" ] || abort "$file missing from the zip"
  target="$BYNAME/$part"
  [ -e "$target" ] || abort "partition $part not found"

  size=$(wc -c < "$file" | tr -d ' ')
  blocks=$(( (size + 4095) / 4096 ))
  ui_print "- flashing $part.img ($size bytes)"
  dd if="$file" of="$target" bs=4096 count=$blocks || abort "dd to $part failed"

  # Read back and compare, so a truncated or read-only partition cannot pass.
  if command -v cmp >/dev/null 2>&1; then
    dd if="$target" bs=4096 count=$blocks 2>/dev/null | cmp - "$file" >/dev/null \
      || abort "$part does not match after writing"
    ui_print "  $part verified"
  else
    ui_print "  $part written (no cmp available to verify)"
  fi
}

ui_print "vayu-mainline kernel"
ui_print "- name: __KERNEL_NAME__"

mkdir -p /tmp/vayu-kernel
unzip -o "$ZIP" boot.img dtbo.img -d /tmp/vayu-kernel >/dev/null 2>&1 \
  || abort "could not unpack the zip"

flash boot /tmp/vayu-kernel/boot.img
flash dtbo /tmp/vayu-kernel/dtbo.img
rm -rf /tmp/vayu-kernel

sync
ui_print "- done; reboot to boot the new kernel"
"""


def release_name(version: str, builder: str, device: str, day: str) -> str:
    return f"{version}-{builder}-{device}-{day}"


def build_zip(out: Path, files: dict[str, bytes], kernel_name: str,
              day: str) -> None:
    """Write a deterministic zip: same inputs, same bytes."""
    stamp = tuple(int(x) for x in day.split("-")) + (0, 0, 0)
    # 2026-10-21 -> (2026, 10, 21, 0, 0, 0)
    info_date = (max(stamp[0], 1980), stamp[1], stamp[2], 0, 0, 0)

    def add(archive: zipfile.ZipFile, name: str, data: bytes,
            mode: int) -> None:
        info = zipfile.ZipInfo(name, date_time=info_date)
        info.external_attr = mode << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, data)

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w") as archive:
        add(archive, "META-INF/com/google/android/update-binary",
            UPDATE_BINARY.replace("__KERNEL_NAME__", kernel_name).encode(),
            0o100755)
        add(archive, "META-INF/com/google/android/updater-script",
            UPDATER_SCRIPT.encode(), 0o100644)
        for name, data in files.items():
            add(archive, name, data, 0o100644)


def cmd_build(args: argparse.Namespace) -> int:
    boot = Path(args.boot).read_bytes()
    if boot[:8] != mkbootimg.MAGIC:
        print(f"{args.boot} is not an Android boot image", file=sys.stderr)
        return 1
    boot_info = mkbootimg.parse(boot)
    if boot_info["header_version"] != 2:
        print("expected a header-v2 boot image", file=sys.stderr)
        return 1

    if args.dtbo:
        dtbo = Path(args.dtbo).read_bytes()
    else:
        # A valid DTBO table with no entries: ABL parses it and applies no
        # overlays, which is what a self-contained mainline DTB wants. The
        # vendor image's single 291 KB base DTB at id 0 is deliberately not
        # mirrored - it would be applied on top of our DTB as an overlay.
        dtbo = mkdtbo.build([], args.dtbo_size)
        print(f"dtbo.img: {args.dtbo_size:,} bytes, DTBO table with 0 entries "
              f"(no vendor overlays applied over the mainline DTB)")

    name = release_name(args.version, args.builder, args.device, args.date)
    out = Path(args.output) if args.output else Path(f"{name}.zip")
    kernel_name = args.kernel_name or args.version

    build_zip(out, {"boot.img": boot, "dtbo.img": dtbo}, kernel_name, args.date)
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
    print(f"  boot.img {len(boot):,} bytes, dtbo.img {len(dtbo):,} bytes")
    print(f"  release name: {name}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    path = Path(args.zip)
    failures: list[str] = []

    def check(condition: bool, message: str) -> None:
        if condition:
            print(f"ok   {message}")
        else:
            print(f"FAIL {message}")
            failures.append(message)

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        check("boot.img" in names, "zip carries boot.img")
        check("dtbo.img" in names, "zip carries dtbo.img")
        check("META-INF/com/google/android/update-binary" in names,
              "zip carries a TWRP update-binary")
        check("META-INF/com/google/android/updater-script" in names,
              "zip carries an updater-script")
        if failures:
            print("\nzip is incomplete", file=sys.stderr)
            return 1

        boot = archive.read("boot.img")
        dtbo = archive.read("dtbo.img")
        binary = archive.read(
            "META-INF/com/google/android/update-binary").decode()

    info = mkbootimg.parse(boot)
    check(info["header_version"] == 2, "boot.img inside the zip is header v2")
    check(info["header_size"] == mkbootimg.V2_HEADER_SIZE,
          f"header size is {mkbootimg.V2_HEADER_SIZE}")
    check(info["kernel"][56:60] == b"ARMd", "boot.img kernel is an arm64 Image")
    check(info["dtb"][:4] == b"\xd0\x0d\xfe\xed", "boot.img carries a DTB")
    check(len(dtbo) == args.dtbo_size,
          f"dtbo.img is {args.dtbo_size:,} bytes (got {len(dtbo):,})")
    dtbo_info = mkdtbo.describe(dtbo)
    check(dtbo_info["magic"] == mkdtbo.MAGIC,
          "dtbo.img carries a valid DTBO table header")
    check(dtbo_info["count"] == 0,
          f"dtbo table has no overlays (got {dtbo_info['count']})")
    check("flash boot" in binary and "flash dtbo" in binary,
          "update-binary flashes both boot and dtbo")

    if args.expect_boot:
        check(boot == Path(args.expect_boot).read_bytes(),
              "boot.img in the zip is byte-identical to the build output")
    if args.kernel_release:
        check(args.kernel_release.encode() in info["kernel"],
              f"kernel carries {args.kernel_release}")

    if failures:
        print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
        return 1
    print("\nzip parses, both payloads are well formed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="write the flashable zip")
    b.add_argument("--boot", required=True, help="header-v2 boot.img")
    b.add_argument("--dtbo", help="dtbo.img to flash (default: a blank one)")
    b.add_argument("--dtbo-size", type=lambda v: int(v, 0),
                   default=DTBO_PARTITION_SIZE)
    b.add_argument("--version", required=True, help="kernel version, e.g. 6.18.32")
    b.add_argument("--builder", default="kyler084")
    b.add_argument("--device", default=DEVICE)
    b.add_argument("--date", default=date_cls.today().isoformat())
    b.add_argument("--kernel-name", help="name printed by the installer")
    b.add_argument("-o", "--output", help="zip path (default: <release name>.zip)")
    b.set_defaults(func=cmd_build)

    v = sub.add_parser("verify", help="unpack and check the zip")
    v.add_argument("--zip", required=True)
    v.add_argument("--expect-boot", help="boot.img the zip must contain")
    v.add_argument("--kernel-release", help="string the kernel must carry")
    v.add_argument("--dtbo-size", type=lambda x: int(x, 0),
                   default=DTBO_PARTITION_SIZE)
    v.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
