# Releases

Every kernel release is a GitHub release whose asset is a TWRP-flashable zip
that writes **both** `boot` and `dtbo`.

## Naming

```
<kernel version>-<builder>-<device>-<date>.zip
6.18.32-kyler084-vayu-2026-10-21.zip
```

| Field | Where it comes from |
| --- | --- |
| kernel version | first field of `include/config/kernel.release` (`6.18.32`) |
| builder | the builder part of `CONFIG_LOCALVERSION="-vayu-kyler084"`, so the file name cannot drift from the name Settings shows |
| device | `vayu` |
| date | build date, UTC, `YYYY-MM-DD` |

The release tag is the same string without `.zip`. Releases are published by
`.github/workflows/build.yml` when it runs with `release: true`, or on a `v*`
tag push, and only after the build, the kernel-name assertion and the zip
verification have all passed.

## What is inside the zip

```
META-INF/com/google/android/update-binary   shell installer for TWRP
META-INF/com/google/android/updater-script  #MAGIC, flashing is done by update-binary
boot.img                                    header v2, kernel + DTB (+ ramdisk)
dtbo.img                                    valid DTBO table, 32 MiB partition
```

`update-binary` resolves `/dev/block/bootdevice/by-name` (falling back to
`/dev/block/by-name`), writes each image with `dd`, then reads the partition
back and compares it with the file, so a short write or a read-only partition
fails the install instead of reporting success.

## dtbo policy

The zip always flashes `dtbo.img`, because on this device that partition is
where the kernel's device tree comes from: the 5.4 kernel's `boot.img` has
`dtb_size` 0 and its `dtbo.img` is a one-entry DTBO table holding the tree.
Releases copy that layout exactly - `boot.img` without a DTB, `dtbo.img` a
32 MiB partition holding a one-entry table with `sm8150-xiaomi-vayu.dtb` at id
0, rev 0, the same ids the vendor image uses.

A blank table would leave the kernel with no device tree at all, which is why
it is not the default (`mkdtbo.py build` with no `--dtb`, and
`mkrelease.py build` with no `--dtb`/`--dtbo`, still emit one for
inspection).

## The AVB footer

The footer is **required**, and that was measured the hard way. Flashing an image
without one and letting the phone reboot put it back in fastboot in about a
second, and the bootloader said why without ever entering the kernel:

```
fastboot boot vayu-boot.img
Booting   FAILED (remote: 'Failed to load/authenticate boot image: Load Error')
```

So `mkbootimg.py` and `mkdtbo.py` pad to the partition size and append a footer
(`--avb-config configs/avb-vayu.json`), `avb.py` reads it back and recomputes
the digest, and the release verifier refuses a zip whose payloads lack one.

No signing key is involved, because the device's own vbmeta uses **algorithm
NONE**: the footer carries a salted SHA-256 of the image in a hash descriptor
and nothing else. It proves the image is intact, not who built it - exactly what
the 5.4 image on this phone ships with.

| | boot | dtbo |
| --- | --- | --- |
| partition | 134,217,728 bytes | 33,554,432 bytes |
| image size | the payload, page-aligned | 294,912 (72 pages) |
| vbmeta | 704 bytes, algorithm NONE | 640 bytes, algorithm NONE |

The salts are the device's (`configs/avb-vayu.json`), which keeps the layout
byte-identical to the stock partition apart from avbtool's version string.

## Ramdisk

Releases carry **our own ramdisk**: CI cross-compiles
[initramfs/init.c](../initramfs/init.c) to a static aarch64 binary and packs it
with `scripts/mkinitramfs.py --lz4`, the same container the stock image uses.
It mounts the pseudo filesystems, prints `uname` and the cmdline, lists
`/sys/fs/pstore`, and idles as pid 1 - enough to complete a boot and to recover
a log on a device with no UART, with no vendor bytes involved.

The device's stock ramdisk is an LZ4 legacy frame of 1,731,405 bytes, and
`mkbootimg.py --ramdisk-from-boot backup/boot-now.img` copies exactly that
payload instead, when the goal is to reach Android userspace:

```bash
python3 scripts/mkbootimg.py build \
    --kernel arch/arm64/boot/Image \
    --dtb arch/arm64/boot/dts/qcom/sm8150-xiaomi-vayu.dtb \
    --ramdisk-from-boot backup/boot-now.img \
    --partition-size 0x8000000 -o boot.img
python3 scripts/mkrelease.py build --boot boot.img --version 6.18.32 \
    --builder kyler084 --device vayu --date 2026-10-21 -o release.zip
```

`mkbootimg.py verify` reports which compression it found, so a gzip ramdisk
slipping in where the device expects LZ4 is visible rather than silent.
