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

## Signing and the AVB footer

The released images are **unsigned**: there is no AVB footer and no vbmeta.
The reference images on the device carry one - `boot-now.img` has a 704-byte
`AVB0` vbmeta at offset 56,971,264 and an `AVBf` footer in the last 64 bytes of
the 128 MiB partition; `device/dtbo.img` has a 640-byte vbmeta at 294,912 and
its footer at the end of its 32 MiB partition - and both are signed with keys
this repo does not have and cannot derive.

Writing a footer signed by anything else would be worse than writing none: a
bootloader that finds a footer will verify it, while an image without one is
accepted when verification is disabled. The 5.4 kernel that runs on this phone
was itself packaged unsigned and unpadded (56,176,640 bytes for `boot.img`),
which is the strongest evidence that this device's bootloader does not need a
footer when unlocked. If the vendor key ever becomes available,
`mkbootimg.py`/`mkrelease.py` can gain an `avbtool` step and the layout above
is the one to reproduce.

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
